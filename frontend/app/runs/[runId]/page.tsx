"use client";

import { CheckCircle2, Clock3, FileKey2, LockKeyhole, ServerCog } from "lucide-react";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { LoadingCard, Notice } from "@/components/Feedback";
import { F4Shell, StateLabel, formatPlanTime } from "@/components/planning/F4Shell";
import { workflowRunSchema } from "@/features/planning/schema";
import { apiFetchContract, presentError } from "@/lib/api/client";

export default function WorkflowRunPage() {
  const { runId } = useParams<{ runId: string }>();
  const run = useQuery({ queryKey: ["f4-run", runId], queryFn: () => apiFetchContract(workflowRunSchema, `/api/v1/workflow-runs/${runId}`), retry: false });
  return (
    <F4Shell eyebrow="F4 · 可信运行记录" title="能解释过程，但不暴露秘密" description="这里只展示任务边界、公开策略版本和结果事件。原始材料全文、模型密钥、系统提示与推理过程不会出现在页面。" backHref={run.data ? `/courses/${run.data.course_id}/workspace` : "/courses"}>
      {run.isPending ? <LoadingCard label="正在读取脱敏运行记录…" /> : run.error ? <Notice tone="error" {...presentError(run.error)} /> : run.data ? (
        <>
          <section className="f4-run-hero">
            <div><span className="f4-run-icon"><ServerCog size={25} /></span><p className="eyebrow">{run.data.task_type}</p><h2>复习计划生成运行</h2><p>运行编号：{run.data.id}</p></div>
            <div><StateLabel status={run.data.status} /><span><Clock3 size={14} />{formatPlanTime(run.data.started_at)}</span></div>
          </section>
          <div className="f4-run-grid">
            <section className="f4-card"><div className="f4-card-head"><div><p className="eyebrow">范围快照</p><h2>本次允许使用什么</h2></div><LockKeyhole size={21} /></div><dl className="f4-run-data">{Object.entries(run.data.scope_snapshot).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{typeof value === "boolean" ? (value ? "是" : "否") : String(value)}</dd></div>)}</dl></section>
            <section className="f4-card"><div className="f4-card-head"><div><p className="eyebrow">策略版本</p><h2>以后可以按版本追溯</h2></div><FileKey2 size={21} /></div><dl className="f4-run-data">{Object.entries(run.data.policy_versions).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{String(value)}</dd></div>)}</dl></section>
          </div>
          <section className="f4-run-timeline"><div className="f4-section-heading"><div><p className="eyebrow">事件时间线</p><h2>公开、有限、可解释</h2></div><p>{run.data.jobs.length} 个后台任务，均不展示 Prompt 与思维链。</p></div>{run.data.events.map((event) => <article key={event.id}><span><CheckCircle2 size={16} /></span><div><strong>{event.message}</strong><p>{event.event_type} · {formatPlanTime(event.created_at)}</p></div></article>)}</section>
          <section className="f4-redaction-rule"><LockKeyhole size={19} /><div><strong>脱敏检查通过</strong><p>页面没有 API Key、Cookie、Authorization、系统提示或原始材料全文。`[REDACTED]` 表示该字段被策略主动遮蔽。</p></div></section>
        </>
      ) : null}
    </F4Shell>
  );
}
