import { expect, test, type Page } from "@playwright/test";

async function resetF5(page: Page, next: string) {
  await page.goto(`/login?next=${encodeURIComponent(next)}`);
  await page.getByLabel("邀请码").fill("F5-DEMO-2026");
  await page.getByRole("button", { name: "进入材料工作台" }).click();
  await expect(page).toHaveURL(next);
}

test("F5 controlled hub is explicit and absent from ordinary navigation", async ({ page }) => {
  await resetF5(page, "/courses/demo-course-f4/workspace");
  await expect(page.getByRole("link", { name: "能力总览" })).toHaveCount(0);
  await page.goto("/controlled");
  await expect(page.getByText("F5 受控能力 · 合同 Mock · 已知资源 ID")).toBeVisible();
  await expect(page.getByRole("heading", { name: "能力可以很强，入口必须克制" })).toBeVisible();
  await expect(page.getByText("普通主导航没有这些入口")).toBeVisible();
});

test("F5 subjective assessment never auto-grades and updates explainable interval", async ({ page }) => {
  await resetF5(page, "/controlled/courses/demo-course-f5/practice");
  await expect(page.getByText("建议 2 天后复习", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "生成主观练习" }).click();
  await page.getByLabel("我的回答").fill("外层函数的输入本身在变化，所以外层变化率还要乘以内层变化率。");
  await page.getByLabel("反思与下一步").fill("还需要补充课堂例题作为材料证据。");
  await page.getByRole("button", { name: "提交自评与反思" }).click();
  await expect(page.getByText("自评已记录，没有自动判定对错")).toBeVisible();
  await expect(page.getByText("automatic_correctness = null", { exact: false })).toBeVisible();
  await expect(page.getByText("建议 4 天后复习", { exact: false })).toBeVisible();
  await expect(page.getByText("subjective_assessment_count").locator(".."), "adaptive interval must expose evidence").toContainText("1");
});

test("F5 external calendar requires provider, OAuth scope and per-write confirmation", async ({ page }) => {
  await resetF5(page, "/controlled/external-calendar");
  await page.getByRole("button", { name: "验证未配置状态" }).click();
  await expect(page.getByText("外部日历 Provider 尚未配置。")).toBeVisible();
  await page.getByRole("button", { name: "查看授权范围" }).click();
  await expect(page.getByText("calendar.events.write", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "完成演示授权" }).click();
  await expect(page.getByText("令牌只保存在后端", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "创建外部同步提案" }).click();
  await page.getByText("异常保护验证（仅合同 Mock）").click();
  await page.getByRole("button", { name: "模拟确认过期" }).click();
  await expect(page.getByText("外部同步确认已过期，请重新预览影响。")).toBeVisible();
  await page.getByRole("button", { name: "模拟版本冲突" }).click();
  await expect(page.getByText("同步提案已经变化，请重新预览影响。")).toBeVisible();
  await page.getByRole("button", { name: "查看本次影响" }).click();
  await expect(page.getByRole("heading", { name: "将写入外部日历" })).toBeVisible();
  await page.getByRole("button", { name: "确认本次同步" }).click();
  await expect(page.getByText("已按本次确认写入外部日历。")).toBeVisible();
  await page.getByRole("button", { name: "模拟重复确认" }).click();
  await expect(page.getByText("确认无效或已经使用。")).toBeVisible();
  await page.getByRole("button", { name: "检查外部变化" }).click();
  await expect(page.getByText("尚未应用到内部日历", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "查看本次影响" }).click();
  await expect(page.getByRole("heading", { name: "将更新内部日历" })).toBeVisible();
  await page.getByRole("button", { name: "确认本次同步" }).click();
  await expect(page.getByText("已按本次确认把外部变更应用到内部日历。")).toBeVisible();
  await page.getByRole("button", { name: "撤销外部同步" }).click();
  await expect(page.getByText("历史状态保留", { exact: false })).toBeVisible();
});

test("F5 organization is aggregate-only and cross-course link is explicit and revocable", async ({ page }) => {
  await resetF5(page, "/admin/organizations/organization-f5");
  await expect(page.getByText("原始学习内容：未包含")).toBeVisible();
  await page.getByRole("button", { name: "验证学习者无权限" }).click();
  await expect(page.getByText("只有组织管理员能查看聚合数据。")).toBeVisible();
  await page.getByRole("button", { name: "添加演示学习者" }).click();
  await page.getByRole("button", { name: "创建第二班" }).click();
  await page.getByRole("button", { name: "加入第二班" }).click();
  await page.getByRole("button", { name: "分配演示课程" }).click();
  await expect(page.getByText("课程已分配给第二班")).toBeVisible();
  await page.getByRole("link", { name: "跨课关联", exact: true }).click();
  await page.getByRole("button", { name: "创建显式关联" }).click();
  await expect(page.getByText("跨课关系已记录")).toBeVisible();
  await page.getByRole("button", { name: "撤销关系" }).click();
  await expect(page.getByText("已撤销", { exact: true })).toBeVisible();
});

test("F5 SFT blocks launch until five gates pass and governance stays aggregated", async ({ page }) => {
  await resetF5(page, "/admin/sft/sft-project-f5");
  await page.getByRole("button", { name: "验证未过门时阻止发起" }).click();
  await expect(page.getByText("SFT 前置门尚未全部通过", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "1. 授权一条来源" }).click();
  await page.getByRole("button", { name: "2. 冻结数据快照" }).click();
  await page.getByRole("button", { name: "3. 记录独立评测" }).click();
  await expect(page.locator(".f5-gate-grid .passed")).toHaveCount(5);
  await page.getByRole("button", { name: "4. 发起训练" }).click();
  await expect(page.getByText("训练任务已提交给 Mock Provider", { exact: false })).toBeVisible();
  await expect(page.getByText("已提交训练", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "治理", exact: true }).click();
  await expect(page.getByText("治理数据已限制为聚合指标")).toBeVisible();
  await expect(page.getByText("无 API Key、OAuth Token", { exact: false })).toBeVisible();
});
