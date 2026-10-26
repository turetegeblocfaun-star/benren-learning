import { expect, test, type Page } from "@playwright/test";

const enabled = process.env.REAL_INTEGRATION === "1";
const invite = process.env.REAL_INTEGRATION_INVITE ?? "";

async function login(page: Page) {
  await page.goto("/login?next=%2Fcourses");
  await page.getByLabel("邀请码").fill(invite);
  await page.getByRole("button", { name: "进入材料工作台" }).click();
  await expect(page).toHaveURL(/\/courses$/);
}

async function ensureUsableCourse(page: Page) {
  const origin = new URL(page.url()).origin;
  const listCourses = async () => {
    const response = await page.request.get("/api/v1/courses?limit=100");
    expect(response.ok()).toBeTruthy();
    return response.json() as Promise<Array<{ id: string; material_counts: Record<string, number> }>>;
  };
  const runId = Date.now().toString();
  const created = await page.request.post("/api/v1/courses", {
    headers: {
      "Idempotency-Key": `real-integration-course-${runId}`,
      Origin: origin,
    },
    data: { temporary_title: "前后端联调验收课程" },
  });
  expect(created.status()).toBe(201);
  const course = await created.json() as { id: string };
  const uploaded = await page.request.post(`/api/v1/courses/${course.id}/material-batches`, {
    headers: {
      "Idempotency-Key": `real-integration-material-${runId}`,
      Origin: origin,
    },
    multipart: {
      manifest: JSON.stringify({
        items: [{
          client_item_id: `integration-text-${runId}`,
          declared_type: "text",
          display_name: "联调验收课堂文字.txt",
          text: "光合作用将光能转化为化学能。叶绿体利用二氧化碳和水合成有机物，并释放氧气。",
        }],
      }),
    },
  });
  expect(uploaded.status()).toBe(202);

  await expect.poll(async () => {
    const response = await page.request.get(`/api/v1/courses/${course.id}`);
    if (!response.ok()) return 0;
    const value = await response.json() as { material_counts: Record<string, number> };
    return value.material_counts.usable ?? 0;
  }, { timeout: 120_000, intervals: [1_000, 2_000, 3_000] }).toBeGreaterThan(0);
  return (await listCourses()).find((item) => item.id === course.id)!;
}

test.describe("real frontend/backend integration", () => {
  test.skip(!enabled || !invite, "set REAL_INTEGRATION=1 and REAL_INTEGRATION_INVITE");
  test.setTimeout(360_000);

  test("material context becomes note, graph, quiz, Tutor, plan and truthful provider state", async ({ page }) => {
    await login(page);
    const course = await ensureUsableCourse(page);
    const courseId = course.id;

    const assetsResponse = await page.request.get(`/api/v1/courses/${courseId}/learning-assets?limit=100`);
    const assets = await assetsResponse.json() as Array<{ id: string; asset_type: string; status: string }>;
    const existingNote = assets.find((item) => item.asset_type === "note" && item.status !== "failed");
    if (existingNote) {
      await page.goto(`/courses/${courseId}/notes/${existingNote.id}`);
    } else {
      await page.goto(`/courses/${courseId}/workspace`);
      await page.getByRole("button", { name: "整理结构笔记" }).click();
    }
    await expect(page).toHaveURL(new RegExp(`/courses/${courseId}/notes/`), { timeout: 30_000 });
    await expect(page.locator(".f3-note-section").first()).toBeVisible({ timeout: 180_000 });
    await expect(page.getByRole("link", { name: "查看课堂来源" }).first()).toBeVisible();
    const noteUrl = page.url();

    const graphResponse = await page.request.get(`/api/v1/courses/${courseId}/learning-assets?limit=100`);
    const currentAssets = await graphResponse.json() as Array<{ id: string; asset_type: string; status: string }>;
    const existingGraph = currentAssets.find((item) => item.asset_type === "graph" && item.status !== "failed");
    if (existingGraph) await page.goto(`/courses/${courseId}/graph/${existingGraph.id}`);
    else await page.getByRole("button", { name: "用当前版本生成图谱" }).click();
    await expect(page).toHaveURL(new RegExp(`/courses/${courseId}/graph/`), { timeout: 30_000 });
    await expect(page.getByRole("img")).toBeVisible({ timeout: 180_000 });
    await page.getByRole("button", { name: "概念列表" }).click();
    await expect(page.locator(".f3-concept-list article").first()).toBeVisible();

    await page.goto(noteUrl);
    const existingQuiz = page.getByRole("link", { name: "打开已有测验" });
    const generateQuiz = page.getByRole("button", { name: "生成客观测验" });
    await expect(existingQuiz.or(generateQuiz)).toBeVisible();
    if (await existingQuiz.count()) await existingQuiz.click();
    else await generateQuiz.click();
    await expect(page).toHaveURL(new RegExp(`/courses/${courseId}/quizzes/`), { timeout: 30_000 });
    let firstOption = page.locator(".f3-option").first();
    const generateNewQuiz = page.getByRole("button", { name: "生成一组新题" });
    await expect(firstOption.or(generateNewQuiz)).toBeVisible({ timeout: 180_000 });
    if (await generateNewQuiz.count()) {
      await generateNewQuiz.click();
      await expect(page).toHaveURL(new RegExp(`/courses/${courseId}/quizzes/`));
      firstOption = page.locator(".f3-option").first();
    }
    await expect(firstOption).toBeVisible({ timeout: 180_000 });
    await expect(firstOption.locator("strong")).not.toHaveText("");
    await firstOption.click();
    await page.getByRole("button", { name: "提交当前答案" }).click();
    const answerHeading = page.getByText("正确答案：", { exact: false });
    await expect(answerHeading).toBeVisible({ timeout: 30_000 });
    const correctAnswer = (await answerHeading.textContent())?.replace("正确答案：", "").trim() ?? "";
    if (await page.getByText("这次还没答对").count()) {
      await page.getByRole("link", { name: "进入错题重练" }).click();
      await page.getByRole("button", { name: new RegExp(`^${correctAnswer}`) }).click();
      await page.getByRole("button", { name: "提交重练答案" }).click();
      await expect(page.getByText("本次重练正确", { exact: false })).toBeVisible();
    }

    await page.goto(noteUrl);
    const existingTutor = page.getByRole("link", { name: "打开已有 Tutor" });
    const startTutor = page.getByRole("button", { name: "开始引导式 Tutor" });
    await expect(existingTutor.or(startTutor)).toBeVisible();
    if (await existingTutor.count()) await existingTutor.click();
    else await startTutor.click();
    await expect(page).toHaveURL(new RegExp(`/courses/${courseId}/tutor/`), { timeout: 30_000 });
    await page.getByLabel("本轮回答").fill("请只依据我上传的资料，用一个问题引导我检查核心概念。");
    await page.getByRole("button", { name: "发送本轮回答" }).click();
    await expect(page.locator(".f3-turn").last()).toContainText("你的回答", { timeout: 30_000 });
    await expect(page.locator(".f3-turn").last().locator(".f3-tutor-reply:not(.f3-tutor-running) p")).not.toHaveText("", { timeout: 180_000 });

    await page.goto(`/courses/${courseId}/workspace`);
    const createPlan = page.getByRole("button", { name: "生成可确认计划" });
    const existingPlan = page.getByRole("link", { name: "查看待确认计划" });
    await expect(createPlan.or(existingPlan)).toBeVisible();
    if (await createPlan.count()) await createPlan.click();
    else await existingPlan.click();
    await expect(page).toHaveURL(new RegExp(`/courses/${courseId}/plans/`), { timeout: 30_000 });
    await expect(page.getByText("外部日历写入关闭")).toBeVisible({ timeout: 180_000 });
    const confirmation = page.getByRole("button", { name: "查看影响并确认" });
    if (await confirmation.isEnabled()) {
      await confirmation.click();
      await expect(page.getByRole("dialog")).toBeVisible();
      await expect(page.getByText("不会写入", { exact: false })).toBeVisible();
      await page.getByRole("button", { name: "确认并写入内部日历" }).click();
      await expect(page.getByText("内部日历新增 1 条事件", { exact: false })).toBeVisible();
    }

    await page.goto("/integration");
    for (const label of ["FastAPI", "数据库", "后台 Worker", "CSRF 来源保护"]) await expect(page.getByText(label, { exact: true })).toBeVisible();
    await expect(page.getByText("deepseek", { exact: false })).toBeVisible();
    await page.goto("/controlled/external-calendar");
    await expect(page.getByText("外部日历暂不可用")).toBeVisible();
    await page.getByRole("button", { name: "验证未配置状态" }).click();
    await expect(page.getByText("Provider", { exact: false }).last()).toBeVisible();
  });
});
