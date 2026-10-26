import { expect, test } from "@playwright/test";

const demoInvite = "F2-DEMO-2026";

async function enterMaterials(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByLabel("邀请码").fill(demoInvite);
  await page.getByRole("button", { name: /进入材料工作台/ }).click();
  await expect(page.getByRole("heading", { name: "让材料替这门课命名" })).toBeVisible();
  await expect(page.getByText("当前课程", { exact: true })).toHaveCount(0);
}

test("F2 homepage opens the upload entrance without a preset course", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "让材料替这门课命名" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "添加这一课的原始材料" })).toBeVisible();
  await expect(page.getByText("当前课程", { exact: true })).toHaveCount(0);
  await expect(page.getByLabel("选择音频文件")).toBeVisible();
  const documentInput = page.getByLabel("选择Word / PDF / Markdown");
  await expect(documentInput).toBeVisible();
  await expect(documentInput).toHaveAttribute("accept", /\.docx/);
  await expect(documentInput).toHaveAttribute("accept", /\.pdf/);
  await expect(documentInput).toHaveAttribute("accept", /\.md/);
});

test("F2 mixed materials complete correction, deletion, naming, context and source", async ({ page }) => {
  await enterMaterials(page);

  await page.getByLabel("选择音频文件").setInputFiles({ name: "课堂音频.m4a", mimeType: "audio/mp4", buffer: Buffer.from("audio") });
  await page.getByLabel("选择Word / PDF / Markdown").setInputFiles({ name: "课堂提纲.md", mimeType: "text/markdown", buffer: Buffer.from("text") });
  await page.getByLabel("选择图片（板书）").setInputFiles({ name: "板书.png", mimeType: "image/png", buffer: Buffer.from("board") });
  await page.getByLabel("选择图片（手写笔记）").setInputFiles({ name: "手写笔记.webp", mimeType: "image/webp", buffer: Buffer.from("note") });

  await expect(page.getByRole("button", { name: "移除待上传文件 板书.png" })).toBeVisible();
  await page.getByRole("button", { name: "移除待上传文件 板书.png" }).click();
  await expect(page.getByText(/板书图片 · 板书\.png/)).toHaveCount(0);
  await page.getByLabel("选择图片（板书）").setInputFiles({ name: "板书.png", mimeType: "image/png", buffer: Buffer.from("board") });

  await page.getByRole("button", { name: "上传并开始识别" }).click();
  await expect(page.getByText("需要你校正", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /删除资料/ })).toHaveCount(4);

  await page.getByRole("link", { name: "查看与校正" }).click();
  await expect(page.getByRole("heading", { name: "手写笔记.webp" })).toBeVisible();
  await page.getByLabel("第 1 段文字").fill("极限描述自变量趋近时，函数值呈现的稳定变化趋势。");
  await page.getByRole("button", { name: "保存校正" }).click();
  await expect(page.getByText("校正已保存为新版本，旧版本仍保留用于追溯。")).toBeVisible();
  await page.getByRole("link", { name: "返回材料页" }).click();

  await expect(page.locator('input[name="title"]').first()).toBeVisible();
  await page.locator('input[name="title"]').first().check();
  await page.getByRole("button", { name: "确认课程名称" }).click();
  await expect(page.getByText(/已成为这门课程的正式名称/)).toBeVisible();

  await page.getByRole("button", { name: "删除资料 板书.png" }).click();
  await expect(page.getByRole("heading", { name: "确认删除这份材料？" })).toBeVisible();
  await expect(page.getByText("删除会产生这些影响", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "确认删除" }).click();
  await expect(page.getByText("板书.png", { exact: true })).toHaveCount(0);

  await page.getByRole("link", { name: /选择材料并验证上下文/ }).click();
  await expect(page.getByRole("heading", { name: "决定这一轮 AI 能看到什么" })).toBeVisible();
  await page.getByRole("button", { name: "创建并验证上下文" }).click();
  await expect(page.getByRole("heading", { name: "材料已切块并完成向量索引" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Embedding 索引" })).toBeVisible();
  await expect(page.getByText("完整覆盖", { exact: true })).toBeVisible();

  await page.getByRole("link", { name: /来源 1/ }).click();
  await expect(page.getByRole("heading", { name: "课堂音频.m4a" })).toBeVisible();
  await expect(page.getByText("模型上下文中的原文片段", { exact: true })).toBeVisible();
});

test("F2 keeps a failed item recoverable without rolling back the batch", async ({ page }) => {
  await enterMaterials(page);
  await page.getByLabel("选择Word / PDF / Markdown").setInputFiles([
    { name: "正常材料.txt", mimeType: "text/plain", buffer: Buffer.from("ok") },
    { name: "识别失败.txt", mimeType: "text/plain", buffer: Buffer.from("retry") },
  ]);
  await page.getByRole("button", { name: "上传并开始识别" }).click();

  await expect(page.getByText("可以使用", { exact: true })).toBeVisible();
  await expect(page.getByText("处理失败", { exact: true })).toBeVisible();
  const failedRow = page.getByRole("article").filter({ hasText: "识别失败.txt" });
  await failedRow.getByRole("button", { name: "重试" }).click();
  await expect(failedRow.getByText("可以使用", { exact: true })).toBeVisible();
});

test("F2 explains an invalid invite and preserves the input", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("邀请码").fill("WRONG-DEMO-CODE");
  await page.getByRole("button", { name: /进入材料工作台/ }).click();
  await expect(page.getByText("邀请码不正确，请检查后再试。")).toBeVisible();
  await expect(page.getByLabel("邀请码")).toHaveValue("WRONG-DEMO-CODE");
});
