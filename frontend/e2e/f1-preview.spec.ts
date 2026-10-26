import { expect, test } from "@playwright/test";

test("F1 homepage starts from materials and does not invent a course", async ({ page }) => {
  await page.goto("/preview/f1");

  await expect(page.getByRole("banner").getByText("前端独立预览", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: /先把材料交给我/ })).toBeVisible();
  await expect(page.getByText("无需先选学科或课程", { exact: true })).toBeVisible();
  await expect(page.getByText("当前课程", { exact: true })).toHaveCount(0);
  await expect(page.getByText("CONTRACT MOCK", { exact: false })).toBeVisible();

  const submit = page.getByRole("button", { name: "上传并识别内容" });
  await expect(submit).toBeDisabled();
  await page.getByLabel("选择学习材料文件").setInputFiles([
    { name: "课堂音频.m4a", mimeType: "audio/mp4", buffer: Buffer.from("audio") },
    { name: "板书.png", mimeType: "image/png", buffer: Buffer.from("image") },
  ]);
  await expect(page.getByText("已选择 2 份材料", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "移除文件 板书.png" })).toBeVisible();
  await page.getByRole("button", { name: "移除文件 板书.png" }).click();
  await expect(page.getByText("已选择 1 份材料", { exact: true })).toBeVisible();
  await submit.click();
  await expect(page.getByText("上传入口验证通过", { exact: true })).toBeVisible();

  const viewport = page.viewportSize();
  if (viewport && viewport.width <= 820) {
    await page.getByRole("button", { name: "打开导航" }).click();
    await expect(page.getByRole("navigation", { name: "学习功能" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("complementary", { name: "学习导航" })).not.toHaveClass(/ws-sidebar-open/);
    await expect(page.getByRole("button", { name: "关闭导航遮罩" })).toHaveCount(0);
  }
});
