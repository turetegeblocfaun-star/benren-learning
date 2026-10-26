import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { WorkspaceShell } from "@/components/layout/WorkspaceShell";

describe("formal workspace shell", () => {
  it("marks the current page and keeps unfinished stages disabled", () => {
    render(<WorkspaceShell><h1>代表工作台</h1></WorkspaceShell>);

    expect(screen.getByRole("button", { name: "上传学习材料" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: /今日工作台/ })).toBeDisabled();
    expect(screen.getByRole("heading", { name: "代表工作台" })).toBeVisible();
  });

  it("opens and closes the mobile navigation without changing routes", () => {
    render(<WorkspaceShell><div>内容</div></WorkspaceShell>);
    fireEvent.click(screen.getByRole("button", { name: "打开导航" }));
    expect(screen.getByRole("complementary", { name: "学习导航" })).toHaveClass("ws-sidebar-open");
    fireEvent.click(screen.getByRole("button", { name: "关闭导航" }));
    expect(screen.getByRole("complementary", { name: "学习导航" })).not.toHaveClass("ws-sidebar-open");
  });
});
