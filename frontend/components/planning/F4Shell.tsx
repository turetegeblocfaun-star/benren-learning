"use client";

import { ArrowLeft, CalendarDays, ClipboardList, Gauge, ListChecks, Settings2 } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";

import { AppShell } from "@/components/AppShell";
import { reviewPlanListSchema, workflowRunListSchema } from "@/features/system/schema";
import { apiFetchContract } from "@/lib/api/client";
import { runtimeStatus } from "@/lib/runtime";

export function F4Shell({
  eyebrow,
  title,
  description,
  children,
  backHref,
  actions,
}: {
  eyebrow: string;
  title: string;
  description: string;
  children: ReactNode;
  backHref?: string;
  actions?: ReactNode;
}) {
  const params = useParams<Record<string, string>>();
  const courseId = params.courseId;
  const plans = useQuery({
    queryKey: ["review-plans", courseId],
    queryFn: () => apiFetchContract(reviewPlanListSchema, `/api/v1/courses/${courseId}/review-plans?limit=100`),
    enabled: Boolean(courseId),
  });
  const runs = useQuery({
    queryKey: ["workflow-runs", courseId],
    queryFn: () => apiFetchContract(workflowRunListSchema, `/api/v1/courses/${courseId}/workflow-runs?limit=100`),
    enabled: Boolean(courseId),
  });
  const planId = plans.data?.find((item) => item.status !== "failed")?.id;
  const runId = runs.data?.[0]?.id;

  return (
    <AppShell>
      <main className="f4-page page-wrap">
        <div className="f4-preview-note" role="status">
          <span aria-hidden="true" /> {runtimeStatus.planning}
        </div>
        <nav className="f4-nav" aria-label="F4 计划闭环">
          {courseId ? <Link href={`/courses/${courseId}/workspace`}><Gauge size={16} />下一步</Link> : <Link href="/courses"><Gauge size={16} />课程记录</Link>}
          {courseId && planId ? <Link href={`/courses/${courseId}/plans/${planId}`}><ClipboardList size={16} />计划详情</Link> : <span><ClipboardList size={16} />暂无计划</span>}
          {courseId ? <Link href={`/courses/${courseId}/calendar`}><CalendarDays size={16} />内部日历</Link> : null}
          {courseId ? <Link href={`/courses/${courseId}/settings`}><Settings2 size={16} />偏好与通知</Link> : null}
          {runId ? <Link href={`/runs/${runId}`}><ListChecks size={16} />运行记录</Link> : <span><ListChecks size={16} />暂无运行记录</span>}
        </nav>
        <div className="page-head f4-head">
          <div className="page-head-copy">
            <p className="eyebrow">{eyebrow}</p>
            <h1>{title}</h1>
            <p className="lede">{description}</p>
          </div>
          <div className="cluster">
            {backHref ? <Link className="button button-secondary" href={backHref}><ArrowLeft size={16} />返回</Link> : null}
            {actions}
          </div>
        </div>
        {children}
      </main>
    </AppShell>
  );
}

export function StateLabel({ status }: { status: string }) {
  const labels: Record<string, string> = {
    ready: "待确认", proposed: "待确认", deferred: "已调整", confirmed: "已确认", scheduled: "已安排",
    cancelled: "已撤销", completed: "已完成", rejected: "已拒绝", queued: "等待发送", open: "处理中", revoked: "已撤回",
  };
  return <span className={`f4-state f4-state-${status}`}>{labels[status] ?? status}</span>;
}

export function formatPlanTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "long", day: "numeric", weekday: "short", hour: "2-digit", minute: "2-digit", hour12: false,
    timeZone: "Asia/Shanghai",
  }).format(new Date(value));
}
