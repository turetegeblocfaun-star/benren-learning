import { expect, test } from "@playwright/test";

const inviteCode = process.env.STAGE1_E2E_INVITE;
test.skip(!inviteCode, "需要 STAGE1_E2E_INVITE 才能验证真实后端流程");

test("user can turn pasted material into a traceable context snapshot", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("邀请码").fill(inviteCode ?? "");
  await page.getByRole("button", { name: "进入材料工作台" }).click();
  await expect(page.getByRole("heading", { name: "添加这一课的原始材料" })).toBeVisible();

  await page.getByLabel("或者直接粘贴课堂文字").fill(
    "第一章 函数基础\n\n函数描述输入与输出之间的确定关系。",
  );
  await page.getByRole("button", { name: "上传并开始识别" }).click();
  await expect(page.getByText("可以使用", { exact: true })).toBeVisible({ timeout: 30_000 });
  const deleteButton = page.getByRole("button", {
    name: /删除资料 粘贴的课堂文字\.txt/,
  }).last();
  await expect(deleteButton).toBeVisible();
  await deleteButton.click();
  await expect(page.getByRole("heading", { name: "确认删除这份材料？" })).toBeVisible();
  await page.getByRole("button", { name: "保留材料" }).click();
  const titleOption = page.locator('input[name="title"]').first();
  if (await titleOption.isVisible({ timeout: 30_000 }).catch(() => false)) {
    await titleOption.check();
    await page.getByRole("button", { name: "确认课程名称" }).click();
    await expect(page.getByText("已成为这门课程的正式名称。")).toBeVisible();
  }

  await page.getByRole("link", { name: "选择材料并验证上下文" }).click();
  await expect(page.getByRole("heading", { name: "决定这一轮 AI 能看到什么" })).toBeVisible();
  await page.getByRole("button", { name: "创建并验证上下文" }).click();

  await expect(page.getByRole("heading", { name: "材料已切块并完成向量索引" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Embedding 索引" })).toBeVisible();
  await expect(page.getByText("完整覆盖", { exact: true })).toBeVisible();
  const sourceLink = page.getByRole("link", { name: /来源 1/ });
  await expect(sourceLink).toBeVisible();
  await sourceLink.click();
  await expect(page.getByRole("heading", { name: "粘贴的课堂文字.txt" })).toBeVisible();
  await expect(page.getByText("模型上下文中的原文片段")).toBeVisible();
});
