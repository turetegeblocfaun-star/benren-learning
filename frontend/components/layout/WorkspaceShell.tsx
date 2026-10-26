"use client";

import {
  Bell,
  BookOpenText,
  BrainCircuit,
  CalendarDays,
  LibraryBig,
  Menu,
  MessageCircleQuestion,
  Network,
  NotebookPen,
  Settings2,
  Sparkles,
  Target,
  UploadCloud,
  X,
} from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useState } from "react";

const navItems = [
  { label: "上传学习材料", icon: UploadCloud, stage: "F1", active: true },
  { label: "今日工作台", icon: BrainCircuit, stage: "F2" },
  { label: "结构化笔记", icon: NotebookPen, stage: "F3" },
  { label: "知识图谱", icon: Network, stage: "F3" },
  { label: "练习与错题", icon: Target, stage: "F3" },
  { label: "引导导师", icon: MessageCircleQuestion, stage: "F3" },
  { label: "复习日历", icon: CalendarDays, stage: "F4" },
];

function ProductMark() {
  return (
    <span className="ws-brand">
      <span className="ws-brand-mark" aria-hidden="true">
        <BookOpenText size={19} strokeWidth={1.8} />
      </span>
      <span>
        <strong>“笨”人学习</strong>
        <small>Learning field notes</small>
      </span>
    </span>
  );
}

export function WorkspaceShell({ children }: { children: ReactNode }) {
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    if (!menuOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [menuOpen]);

  return (
    <div className="ws-shell">
      <a className="skip-link" href="#workspace-main">跳到主要内容</a>

      <aside className={`ws-sidebar ${menuOpen ? "ws-sidebar-open" : ""}`} aria-label="学习导航">
        <div className="ws-sidebar-head">
          <ProductMark />
          <button className="ws-close-menu" type="button" onClick={() => setMenuOpen(false)} aria-label="关闭导航">
            <X size={20} />
          </button>
        </div>

        <nav className="ws-nav" aria-label="学习功能">
          <p className="ws-nav-label">从材料开始</p>
          {navItems.map(({ label, icon: Icon, stage, active }) => (
            <button
              className={`ws-nav-item ${active ? "ws-nav-item-active" : ""}`}
              type="button"
              key={label}
              disabled={!active}
              aria-current={active ? "page" : undefined}
              title={active ? label : `${label}将在 ${stage} 阶段开放`}
            >
              <Icon size={17} strokeWidth={1.8} aria-hidden="true" />
              <span>{label}</span>
              {!active ? <small>{stage}</small> : null}
            </button>
          ))}
        </nav>

        <div className="ws-sidebar-note">
          <span aria-hidden="true"><Sparkles size={16} /></span>
          <div><strong>不用先选课程</strong><p>上传材料后，系统会根据内容建议课程名称。</p></div>
        </div>

        <div className="ws-profile">
          <span className="ws-avatar" aria-hidden="true">学</span>
          <span><strong>试点学习者</strong><small>前端独立预览</small></span>
          <Settings2 size={16} aria-hidden="true" />
        </div>
      </aside>

      {menuOpen ? <button className="ws-overlay" type="button" onClick={() => setMenuOpen(false)} aria-label="关闭导航遮罩" /> : null}

      <div className="ws-body">
        <header className="ws-topbar">
          <button className="ws-menu-button" type="button" onClick={() => setMenuOpen(true)} aria-label="打开导航">
            <Menu size={20} />
          </button>
          <div className="ws-crumbs"><span>开始</span><b>/</b><strong>上传材料</strong></div>
          <div className="ws-top-actions">
            <span className="ws-preview-badge"><span />前端独立预览</span>
            <button className="ws-icon-button" type="button" aria-label="通知将在 F4 阶段开放" disabled>
              <Bell size={18} />
            </button>
          </div>
        </header>
        <main id="workspace-main" className="ws-main">{children}</main>
      </div>
    </div>
  );
}

export function WorkspaceLoading() {
  return (
    <div className="ws-loading" aria-busy="true" aria-live="polite">
      <div className="ws-loading-line ws-loading-title" />
      <div className="ws-loading-line" />
      <div className="ws-loading-grid"><div /><div /><div /></div>
      <span className="sr-only">正在读取代表工作台数据</span>
    </div>
  );
}

export function WorkspaceError({ onRetry }: { onRetry: () => void }) {
  return (
    <section className="ws-error" role="alert">
      <LibraryBig size={26} aria-hidden="true" />
      <div><p className="eyebrow">代表页暂时没有准备好</p><h1>无法读取模拟工作台</h1><p>请重试。这个错误只影响前端预览，不代表后端服务状态。</p></div>
      <button className="ws-button ws-button-primary" type="button" onClick={onRetry}>重新读取</button>
    </section>
  );
}
