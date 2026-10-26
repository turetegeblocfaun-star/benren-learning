import { expect, test, type Page } from "@playwright/test";

async function resetF4(page: Page, next: string) {
  await page.goto(`/login?next=${encodeURIComponent(next)}`);
  await page.getByLabel("邀请码").fill("F4-DEMO-2026");
  await page.getByRole("button", { name: "进入材料工作台" }).click();
  await expect(page).toHaveURL(next);
  await expect(page.getByText("F4 资源发现合同已接入 · 尚未真实联调")).toBeVisible();
}

async function createPlan(page: Page) {
  await resetF4(page, "/courses/demo-course-f4/workspace");
  await expect(page.getByRole("heading", { name: "生成下一次复习计划" })).toHaveCount(1);
  await expect(page.getByRole("heading", { name: "结构化笔记入口" })).toBeVisible();
  await expect(page.getByRole("button", { name: "整理结构化笔记" })).toBeVisible();
  await page.getByRole("button", { name: "生成可确认计划" }).click();
  await expect(page).toHaveURL(/\/plans\/plan-f4$/);
  await expect(page.getByText("0", { exact: true })).toBeVisible();
}

test("F4 unique next action edits time, previews impact, confirms and undoes", async ({ page }) => {
  await createPlan(page);
  await page.getByLabel("调整开始时间").fill("2026-09-03T20:15");
  await page.getByRole("button", { name: "保存新时间" }).click();
  await expect(page.getByText("候选 v2")).toBeVisible();
  await page.getByRole("button", { name: "查看影响并确认" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByText("不会写入；F4 未连接任何外部账号")).toBeVisible();
  await expect(page.getByText("本次确认只对候选时间 v2 生效", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "确认并写入内部日历" }).click();
  await expect(page.getByText("内部日历新增 1 条事件", { exact: false })).toBeVisible();
  await page.getByRole("link", { name: "内部日历", exact: true }).click();
  await expect(page.getByRole("heading", { name: "链式法则 · 闭卷回忆与错题检验" })).toBeVisible();
  await expect(page.getByRole("link", { name: "导出 ICS" })).toHaveAttribute("href", "/api/v1/calendar-events/calendar-event-f4.ics");
  await page.getByRole("button", { name: "撤销安排" }).click();
  await expect(page.getByText("已撤销安排；历史仍保留", { exact: false })).toBeVisible();
  await expect(page.getByText("已撤销", { exact: true })).toBeVisible();
});

test("F4 blocks stale version and expired confirmation without calendar writes", async ({ page }) => {
  await createPlan(page);
  await page.getByText("异常保护验证（仅合同 Mock）").click();
  await page.getByRole("button", { name: "模拟版本冲突" }).click();
  await expect(page.getByText("候选时间已经变化，请刷新后重新预览影响。")).toBeVisible();
  await page.getByRole("button", { name: "模拟确认过期" }).click();
  await expect(page.getByText("确认已过期，请重新查看影响。")).toBeVisible();
  await expect(page.getByText("0", { exact: true })).toBeVisible();
});

test("F4 saves preferences, controls notifications and versions feedback", async ({ page }) => {
  await resetF4(page, "/courses/demo-course-f4/settings");
  await expect(page.getByText("设置会从后端恢复", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "保存学习偏好" }).click();
  await expect(page.getByText("学习偏好已保存为 v1", { exact: false })).toBeVisible();
  await page.getByLabel("提前提醒（分钟）").fill("45");
  await page.getByRole("button", { name: "保存通知偏好" }).click();
  await expect(page.getByText("将提前 45 分钟")).toBeVisible();
  await page.getByLabel("哪里需要核对？").fill("第二段推导缺少内层导数的来源说明。");
  await page.getByRole("button", { name: "提交版本化反馈" }).click();
  await expect(page.getByText("反馈已提交并保留目标版本", { exact: false })).toBeVisible();
  await expect(page.getByText("第二段推导缺少内层导数的来源说明。")).toBeVisible();
  await page.getByRole("button", { name: "撤回" }).click();
  await expect(page.getByText("反馈已撤回，历史状态仍可追溯。")).toBeVisible();
  await expect(page.getByText("已撤回", { exact: true })).toBeVisible();
});

test("F4 completes an event and exposes only redacted workflow data", async ({ page }) => {
  await createPlan(page);
  await page.getByRole("button", { name: "查看影响并确认" }).click();
  await page.getByRole("button", { name: "确认并写入内部日历" }).click();
  await page.getByRole("link", { name: "偏好与通知", exact: true }).click();
  await expect(page.getByText("复习提醒 · 站内")).toBeVisible();
  await expect(page.getByText("等待发送", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "内部日历", exact: true }).click();
  await page.getByRole("button", { name: "标记完成" }).click();
  await expect(page.getByText("已完成复习；计划状态会据此推进。")).toBeVisible();
  await page.getByRole("link", { name: "运行记录" }).click();
  await expect(page.getByText("[REDACTED]", { exact: true })).toBeVisible();
  await expect(page.getByText("脱敏检查通过")).toBeVisible();
  await expect(page.locator("body")).not.toContainText("Authorization: Bearer");
});
