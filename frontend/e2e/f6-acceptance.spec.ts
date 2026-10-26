import { expect, test, type Page } from "@playwright/test";

async function resetF6(page: Page, next: string) {
  await page.goto(`/login?next=${encodeURIComponent(next)}`);
  await page.getByLabel("邀请码").fill("F6-DEMO-2026");
  await page.getByRole("button", { name: "进入材料工作台" }).click();
  await expect(page).toHaveURL(next);
}

test("F6 acceptance center exposes twelve persistent, resettable checks and honest boundaries", async ({ page }) => {
  await resetF6(page, "/acceptance");
  await expect(page.getByRole("heading", { name: "照着 12 步，检查完整学习闭环" })).toBeVisible();
  await expect(page.getByText("尚未真实联调 · 尚未部署", { exact: true })).toBeVisible();
  await expect(page.getByRole("checkbox")).toHaveCount(12);

  const first = page.getByRole("checkbox", { name: /确认预览身份/ });
  const second = page.getByRole("checkbox", { name: /邀请码直达上传/ });
  await first.check();
  await second.check();
  await expect(page.getByText("2 / 12", { exact: true })).toBeVisible();
  await page.reload();
  await expect(first).toBeChecked();
  await expect(second).toBeChecked();
  await page.getByRole("button", { name: "清空勾选" }).click();
  await expect(first).not.toBeChecked();
  await expect(page.getByText("0 / 12", { exact: true })).toBeVisible();
});

test("F6 keyboard flow exposes skip navigation and traps then restores confirmation focus", async ({ page }) => {
  await page.goto("/acceptance");
  await page.keyboard.press("Tab");
  const skipLink = page.getByRole("link", { name: "跳到主要内容" });
  await expect(skipLink).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#page-content")).toBeFocused();

  await resetF6(page, "/courses/demo-course-f4/workspace");
  await page.getByRole("button", { name: "生成可确认计划" }).click();
  const trigger = page.getByRole("button", { name: "查看影响并确认" });
  await trigger.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "关闭确认窗口" })).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(page.getByRole("button", { name: "确认并写入内部日历" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();
});

test("F6 representative pages fit 390, 768, 1280 and 1440 widths without console failures", async ({ page }) => {
  const failures: string[] = [];
  page.on("pageerror", (error) => failures.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") failures.push(message.text());
  });

  for (const width of [390, 768, 1280, 1440]) {
    await page.setViewportSize({ width, height: width <= 768 ? 844 : 960 });
    await page.goto("/acceptance");
    await expect(page.getByRole("heading", { name: "照着 12 步，检查完整学习闭环" })).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, `${width}px should not have horizontal overflow`).toBeLessThanOrEqual(1);
  }

  expect(failures).toEqual([]);
});
