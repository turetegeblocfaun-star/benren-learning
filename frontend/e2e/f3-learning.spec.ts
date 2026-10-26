import { expect, test, type Page } from "@playwright/test";

async function resetF3(page: Page, next: string) {
  await page.goto(`/login?next=${encodeURIComponent(next)}`);
  await page.getByLabel("邀请码").fill("F3-DEMO-2026");
  await page.getByRole("button", { name: "进入材料工作台" }).click();
  await expect(page).toHaveURL(next);
  await expect(page.getByText("资源发现合同已接入 · 尚未真实联调")).toBeVisible();
}

test("F3 note source edit version and graph recovery", async ({ page }) => {
  await resetF3(page, "/courses/demo-course-f3/workspace");
  await page.getByRole("button", { name: "整理结构笔记" }).click();
  await expect(page).toHaveURL(/\/notes\/note-f3$/);
  for (const label of ["上传材料", "材料案例", "官方补充", "AI 推断", "待核对"]) {
    await expect(page.locator(".f3-source-badge", { hasText: label })).toBeVisible();
  }

  await page.getByRole("link", { name: "查看课堂来源" }).first().click();
  await expect(page.getByRole("heading", { name: "模型上下文中的原文片段" })).toBeVisible();
  await page.goBack();
  await page.getByRole("button", { name: "编辑笔记" }).click();
  await page.getByLabel("笔记标题").fill("我修订的链式法则笔记");
  await page.getByLabel("概要").fill("这是人工确认过的新概要，旧版不会被覆盖。");
  await page.getByRole("button", { name: "保存新版本" }).click();
  await expect(page.getByText("当前版本 v2")).toBeVisible();
  await expect(page.getByText("这是人工修订版本")).toBeVisible();

  await page.getByRole("link", { name: "知识图谱" }).click();
  await expect(page.getByText("版本已过期")).toBeVisible();
  await page.getByRole("button", { name: "概念列表" }).click();
  await expect(page.getByRole("heading", { name: "内层导数" })).toBeVisible();
  await expect(page.getByText("需复习")).toBeVisible();
});

test("F3 quiz grades after submit, deduplicates wrongbook and withdraws", async ({ page }) => {
  await resetF3(page, "/courses/demo-course-f3/quizzes/quiz-f3");
  await expect(page.getByText("正确答案：A")).toHaveCount(0);
  await page.getByText("只写成 2(3x+1)", { exact: true }).click();
  await page.getByRole("button", { name: "提交当前答案" }).click();
  await expect(page.getByText("正确答案：A")).toBeVisible();
  await expect(page.getByText("代码按答案键确定", { exact: false })).toBeVisible();
  await page.getByRole("link", { name: "进入错题重练" }).click();
  await expect(page.getByText("错 1 次")).toBeVisible();
  await expect(page.getByText("2(3x+1) 再乘以内层导数 3", { exact: true })).toBeVisible();
  await expect(page.getByText("只写成 2(3x+1)", { exact: true })).toBeVisible();
  await expect(page.getByText("把 3x+1 当作常数", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /A.*2\(3x\+1\).*内层导数 3/ }).click();
  await page.getByRole("button", { name: "提交重练答案" }).click();
  await expect(page.getByText("本次重练正确", { exact: false })).toBeVisible();
  await expect(page.getByText("已纠正", { exact: true }).first()).toBeVisible();
  await page.getByRole("link", { name: "返回查看题目撤回状态" }).click();
  await expect(page.getByText("当前没有可作答题目。")) .toBeVisible();
  await expect(page.getByRole("heading", { name: "题目已撤回" })).toBeVisible();
});

test("F3 text Tutor recovers safely after RAG no-hit", async ({ page }) => {
  await resetF3(page, "/courses/demo-course-f3/tutor/tutor-rag-f3");
  await expect(page.getByText("tutor_rag", { exact: true })).toBeVisible();
  await page.getByLabel("本轮回答").fill("奥赛罗发生在威尼斯的哪一段？");
  await page.getByRole("button", { name: "发送本轮回答" }).click();
  await expect(page.getByText("正在定位所选材料中的相关原文")).toBeVisible();
  await expect(page.getByText("检索无命中；没有使用模型记忆补答案。"), "RAG no_hit must not fall back to model memory").toBeVisible({ timeout: 6_000 });
  await page.getByRole("button", { name: "换成材料内问题" }).click();
  await page.getByRole("button", { name: "发送本轮回答" }).click();
  await expect(page.getByText("3x+1 对 x 的变化率是多少？", { exact: false })).toBeVisible({ timeout: 6_000 });

  await expect(page.getByLabel("本轮回答")).toBeEnabled();
  await expect(page.getByRole("button", { name: "开始录音" })).toHaveCount(0);
  await expect(page.getByText("语音确认门", { exact: true })).toHaveCount(0);

  await page.getByRole("button", { name: /短材料完整上下文/ }).click();
  await expect(page).toHaveURL(/tutor-direct-f3$/);
  await expect(page.getByText("direct_full", { exact: true })).toBeVisible();
});
