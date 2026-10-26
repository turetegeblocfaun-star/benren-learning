import { BookOpenText } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { isContractMock, runtimeStatus } from "@/lib/runtime";

export function Brand() {
  return (
    <span className="brand">
      <span className="brand-mark" aria-hidden="true"><BookOpenText size={20} /></span>
      <span>“笨”人学习</span>
    </span>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="app-shell">
      <header className="site-header">
        <Link href="/courses/new" aria-label="返回材料上传入口"><Brand /></Link>
        <div className="header-meta">
          <Link className="header-link" href="/courses/new">上传资料</Link>
          <Link className="header-link" href="/courses">课程记录</Link>
          <Link className="header-link header-link-primary" href={isContractMock ? "/acceptance" : "/integration"}>{isContractMock ? "最终验收" : "联调验收"}</Link>
          <span className="ws-preview-badge"><span />{runtimeStatus.badge}</span>
          <span className="stage-pill">{runtimeStatus.stage}</span>
        </div>
      </header>
      {children}
    </div>
  );
}

export function StepStrip({ active }: { active: 1 | 2 | 3 }) {
  const steps = ["添加材料", "确认内容", "编排上下文"];
  return (
    <nav className="step-strip" aria-label="材料闭环进度">
      {steps.map((step, index) => {
        const number = (index + 1) as 1 | 2 | 3;
        const className = number === active ? "step step-active" : number < active ? "step step-done" : "step";
        return <div className={className} key={step}><span className="step-no">{number}</span><span>{step}</span></div>;
      })}
    </nav>
  );
}
