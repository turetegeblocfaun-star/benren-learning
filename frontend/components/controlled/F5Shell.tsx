"use client";

import { ArrowLeft, BookCheck, Building2, CalendarSync, GraduationCap, Link2, LockKeyhole, ShieldCheck } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";

import { AppShell } from "@/components/AppShell";
import { LoadingCard, Notice } from "@/components/Feedback";
import { controlledGateContract, type ControlledGate } from "@/features/controlled/gates";
import { organizationListSchema, sftProjectListSchema } from "@/features/controlled/schema";
import { userSchema } from "@/features/materials/schema";
import { courseListSchema } from "@/features/system/schema";
import { apiFetchContract, presentError } from "@/lib/api/client";
import { runtimeStatus } from "@/lib/runtime";

export function F5Shell({ eyebrow, title, description, gate, children, backHref }: {
  eyebrow: string; title: string; description: string; gate?: ControlledGate; children: ReactNode; backHref?: string;
}) {
  const access = useQuery({
    queryKey: ["current-user-access"],
    queryFn: () => apiFetchContract(userSchema, "/api/v1/me"),
    enabled: Boolean(gate),
    retry: false,
  });
  const courses = useQuery({ queryKey: ["courses"], queryFn: () => apiFetchContract(courseListSchema, "/api/v1/courses?limit=100") });
  const organizations = useQuery({ queryKey: ["organizations"], queryFn: () => apiFetchContract(organizationListSchema, "/api/v1/organizations?limit=100") });
  const sftProjects = useQuery({ queryKey: ["sft-projects"], queryFn: () => apiFetchContract(sftProjectListSchema, "/api/v1/sft/projects?limit=100") });
  const links = [
    ["/controlled", ShieldCheck, "能力总览"],
    courses.data?.[0] ? [`/controlled/courses/${courses.data[0].id}/practice`, BookCheck, "主观与自适应"] : null,
    ["/controlled/external-calendar", CalendarSync, "外部日历"],
    organizations.data?.[0] ? [`/admin/organizations/${organizations.data[0].id}`, Building2, "组织聚合"] : null,
    ["/controlled/cross-course", Link2, "跨课关联"],
    sftProjects.data?.[0] ? [`/admin/sft/${sftProjects.data[0].id}`, GraduationCap, "SFT 门禁"] : null,
    ["/admin/governance", LockKeyhole, "治理"],
  ].filter((item): item is [string, typeof ShieldCheck, string] => item !== null);
  const required = gate ? controlledGateContract[gate] : null;
  const enabled = !gate || Boolean(access.data?.capabilities.includes(required!.capability));
  return (
    <AppShell>
      <main className="f5-page page-wrap">
        <div className="f5-preview-note" role="status"><span />{runtimeStatus.controlled}</div>
        <nav className="f5-nav" aria-label="F5 受控能力导航">{links.map(([href, Icon, label]) => <Link href={href} key={href}><Icon size={15} />{label}</Link>)}</nav>
        <div className="page-head f5-head"><div className="page-head-copy"><p className="eyebrow">{eyebrow}</p><h1>{title}</h1><p className="lede">{description}</p></div>{backHref ? <Link className="button button-secondary" href={backHref}><ArrowLeft size={16} />返回</Link> : null}</div>
        {gate && access.isPending ? <LoadingCard label="正在核验角色与能力…" /> : gate && access.error ? <Notice tone="error" {...presentError(access.error)} /> : enabled ? children : <GateClosed gate={gate!} />}
      </main>
    </AppShell>
  );
}

function GateClosed({ gate }: { gate: ControlledGate }) {
  const contract = controlledGateContract[gate];
  return <section className="f5-gate-closed"><LockKeyhole size={31} /><h2>你没有这项受控权限</h2><p>当前会话未获得“{contract.label}”（`{contract.capability}`）。前端会阻止入口，后端仍会在每次请求时再次校验。</p><Link className="button button-secondary" href="/courses">返回课程记录</Link></section>;
}

export function F5Status({ value }: { value: string }) {
  const map: Record<string,string> = { active: "已启用", ready: "待作答", synced: "已同步", proposed: "待确认", revoked: "已撤销", cancelled: "已撤销", draft: "草稿", preparing: "准备中", training_submitted: "已提交训练", granted: "已授权", frozen: "已冻结" };
  return <span className={`f5-status f5-status-${value}`}>{map[value] ?? value}</span>;
}
