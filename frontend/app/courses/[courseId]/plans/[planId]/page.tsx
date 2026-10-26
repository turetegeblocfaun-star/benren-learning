"use client";

import { AlertTriangle, ArrowRight, CalendarCheck2, CalendarClock, CheckCircle2, Clock3, FileClock, Play, RefreshCw, ShieldCheck, SkipForward, XCircle } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { LoadingCard, Notice } from "@/components/Feedback";
import { ConfirmationDialog } from "@/components/planning/ConfirmationDialog";
import { F4Shell, StateLabel, formatPlanTime } from "@/components/planning/F4Shell";
import {
  actionEventSchema,
  calendarCandidateSchema,
  calendarEventSchema,
  calendarEventsSchema,
  confirmationPreviewSchema,
  reviewPlanSchema,
  type ReviewPlan,
  type ConfirmationPreview,
} from "@/features/planning/schema";
import { workflowRunListSchema } from "@/features/system/schema";
import { apiFetchContract, idempotencyKey, jsonBody, presentError } from "@/lib/api/client";
import { isContractMock } from "@/lib/runtime";

function localInputValue(value: string) {
  const date = new Date(value);
  const formatter = new Intl.DateTimeFormat("sv-SE", {
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Shanghai",
  });
  return formatter.format(date).replace(" ", "T");
}

export default function ReviewPlanPage() {
  const { courseId, planId } = useParams<{ courseId: string; planId: string }>();
  const queryClient = useQueryClient();
  const [startAt, setStartAt] = useState("");
  const [preview, setPreview] = useState<ConfirmationPreview | null>(null);
  const [success, setSuccess] = useState("");
  const [diagnosticError, setDiagnosticError] = useState<unknown>(null);
  const confirmationTriggerRef = useRef<HTMLButtonElement>(null);
  const plan = useQuery({
    queryKey: ["f4-plan", planId],
    queryFn: () => apiFetchContract(reviewPlanSchema, `/api/v1/review-plans/${planId}`),
    retry: false,
    refetchInterval: (query) => {
      const data = query.state.data as ReviewPlan | undefined;
      return data && !["ready", "failed", "cancelled"].includes(data.status) ? 750 : false;
    },
  });
  const calendar = useQuery({ queryKey: ["f4-calendar", courseId], queryFn: () => apiFetchContract(calendarEventsSchema, `/api/v1/courses/${courseId}/calendar-events`) });
  const workflowRuns = useQuery({ queryKey: ["workflow-runs", courseId], queryFn: () => apiFetchContract(workflowRunListSchema, `/api/v1/courses/${courseId}/workflow-runs?limit=100`) });
  const candidate = plan.data?.calendar_candidates[0];
  const planRun = workflowRuns.data?.find((item) => item.task_type === "generate_review_plan") ?? workflowRuns.data?.[0];

  useEffect(() => {
    if (candidate && !startAt) setStartAt(localInputValue(candidate.start_at));
  }, [candidate, startAt]);

  const refreshPlan = async () => {
    setPreview(null);
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["f4-plan", planId] }),
      queryClient.invalidateQueries({ queryKey: ["f4-calendar", courseId] }),
      queryClient.invalidateQueries({ queryKey: ["f4-workspace", courseId] }),
      queryClient.invalidateQueries({ queryKey: ["f4-deliveries", courseId] }),
    ]);
  };

  const updateCandidate = useMutation({
    mutationFn: async () => {
      if (!candidate) throw new Error("missing candidate");
      const start = new Date(startAt);
      const end = new Date(start.getTime() + 30 * 60_000);
      return apiFetchContract(calendarCandidateSchema, `/api/v1/calendar-candidates/${candidate.id}`, {
        method: "PATCH", headers: { "If-Match": String(candidate.version), "Idempotency-Key": idempotencyKey("candidate-edit") },
        body: jsonBody({ start_at: start.toISOString(), end_at: end.toISOString(), timezone: "Asia/Shanghai" }),
      });
    },
    onSuccess: async (updated) => { setStartAt(localInputValue(updated.start_at)); setSuccess("时间已更新。旧确认已失效，请重新查看写入影响。"); await refreshPlan(); },
  });

  const rejectCandidate = useMutation({
    mutationFn: () => apiFetchContract(calendarCandidateSchema, `/api/v1/calendar-candidates/${candidate?.id}/reject`, {
      method: "POST", headers: { "If-Match": String(candidate?.version), "Idempotency-Key": idempotencyKey("candidate-reject") },
    }),
    onSuccess: async () => { setSuccess("候选时间已拒绝，没有写入任何日历事件。"); await refreshPlan(); },
  });

  const previewConfirmation = useMutation({
    mutationFn: () => apiFetchContract(confirmationPreviewSchema, `/api/v1/calendar-candidates/${candidate?.id}/confirmation-preview`, {
      method: "POST", headers: { "If-Match": String(candidate?.version) },
    }),
    onSuccess: (value) => { setSuccess(""); setPreview(value); },
  });

  const confirm = useMutation({
    mutationFn: () => apiFetchContract(calendarEventSchema, `/api/v1/calendar-candidates/${candidate?.id}/confirm`, {
      method: "POST", headers: { "If-Match": String(preview?.expected_version), "Idempotency-Key": idempotencyKey("candidate-confirm") },
      body: jsonBody({ confirmation_token: preview?.confirmation_token }),
    }),
    onSuccess: async () => { setSuccess("已确认：内部日历新增 1 条事件，没有写入外部日历。"); await refreshPlan(); },
  });

  const actionEvent = useMutation({
    mutationFn: (eventType: "started" | "skipped" | "completed") => apiFetchContract(actionEventSchema, `/api/v1/review-plans/${planId}/action-events`, {
      method: "POST", headers: { "Idempotency-Key": idempotencyKey(`plan-${eventType}`) }, body: jsonBody({ event_type: eventType, reason: eventType === "skipped" ? "这次不适合，稍后重新安排" : null }),
    }),
    onSuccess: (event) => setSuccess(event.event_type === "skipped" ? "已记录跳过；原记录没有被覆盖。" : "已追加行动记录。"),
  });

  async function simulate(kind: "conflict" | "expired") {
    if (!candidate) return;
    setDiagnosticError(null); setSuccess("");
    try {
      if (kind === "conflict") {
        await apiFetchContract(calendarCandidateSchema, `/api/v1/calendar-candidates/${candidate.id}`, {
          method: "PATCH", headers: { "If-Match": String(Math.max(0, candidate.version - 1)), "Idempotency-Key": idempotencyKey("stale-version-check") },
          body: jsonBody({ start_at: candidate.start_at, end_at: candidate.end_at, timezone: candidate.timezone }),
        });
      } else {
        await apiFetchContract(calendarEventSchema, `/api/v1/calendar-candidates/${candidate.id}/confirm`, {
          method: "POST", headers: { "If-Match": String(candidate.version), "Idempotency-Key": idempotencyKey("expired-token-check") },
          body: jsonBody({ confirmation_token: "expired-f4-token" }),
        });
      }
    } catch (error) { setDiagnosticError(error); }
  }

  const closePreview = useCallback(() => setPreview(null), []);
  const errors = updateCandidate.error ?? rejectCandidate.error ?? previewConfirmation.error ?? confirm.error ?? actionEvent.error ?? diagnosticError;

  if (plan.isPending || (plan.data && !candidate && !["failed", "cancelled"].includes(plan.data.status))) return <F4Shell eyebrow="F4 · 计划详情" title="正在读取计划" description="候选时间与版本以服务端记录为准。"><LoadingCard label="DeepSeek 正在生成复习计划，页面会自动更新…" /></F4Shell>;
  if (plan.error) return <F4Shell eyebrow="F4 · 计划详情" title="还没有可查看的计划" description="计划不会凭空出现，请先从唯一下一步生成。"><Notice tone="error" {...presentError(plan.error)} /><div className="f4-empty-action"><Link className="button button-primary" href={`/courses/${courseId}/workspace`}>返回生成计划 <ArrowRight size={17} /></Link></div></F4Shell>;
  if (!plan.data || !candidate) return null;

  const hasEvent = (calendar.data?.length ?? 0) > 0;
  const editable = !["confirmed", "rejected"].includes(candidate.status);
  return (
    <F4Shell eyebrow="F4 · 计划详情" title="把建议变成你确认的安排" description="系统先给理由和候选时间。你改完时间后必须重新预览影响；只有最后一次明确确认才会写入内部日历。" backHref={`/courses/${courseId}/workspace`} actions={planRun ? <Link className="button button-secondary" href={`/runs/${planRun.id}`}><FileClock size={16} />查看脱敏运行记录</Link> : undefined}>
      <section className="f4-plan-summary">
        <div><p className="eyebrow">下一行动</p><h2>{plan.data.next_action?.reason}</h2><div className="cluster"><span><Clock3 size={15} />{plan.data.next_action?.duration_min} 分钟</span><span><ShieldCheck size={15} />外部日历写入关闭</span></div></div>
        <div className="f4-plan-status"><span>计划状态</span><StateLabel status={plan.data.status} /><small>计划 v{plan.data.version} · 候选 v{candidate.version}</small></div>
      </section>

      {success ? <div className="f4-feedback-space"><Notice tone="success" message={success} /></div> : null}
      {errors ? <div className="f4-feedback-space"><Notice tone="error" {...presentError(errors)} /></div> : null}

      <div className="f4-plan-grid">
        <section className="f4-card">
          <div className="f4-card-head"><div><p className="eyebrow">候选时间 01</p><h2>一次闭卷回忆 + 错题检验</h2></div><StateLabel status={candidate.status} /></div>
          <div className="f4-candidate-time"><CalendarClock size={25} /><div><strong>{formatPlanTime(candidate.start_at)}</strong><span>Asia/Shanghai · 30 分钟</span></div></div>
          <p className="f4-candidate-reason">{candidate.reason}</p>
          <label className="field f4-time-field" htmlFor="candidate-start"><span>调整开始时间</span><input id="candidate-start" className="input" type="datetime-local" value={startAt} onChange={(event) => setStartAt(event.target.value)} disabled={!editable} /></label>
          <div className="cluster f4-candidate-actions">
            <button className="button button-secondary" onClick={() => updateCandidate.mutate()} disabled={!editable || updateCandidate.isPending || !startAt}>{updateCandidate.isPending ? "保存中…" : <><RefreshCw size={16} />保存新时间</>}</button>
            <button ref={confirmationTriggerRef} className="button button-primary" onClick={() => previewConfirmation.mutate()} disabled={!editable || previewConfirmation.isPending}>{previewConfirmation.isPending ? "正在计算影响…" : <><CalendarCheck2 size={17} />查看影响并确认</>}</button>
            <button className="f4-danger-link" type="button" onClick={() => rejectCandidate.mutate()} disabled={!editable || rejectCandidate.isPending}><XCircle size={15} />拒绝这个时间</button>
          </div>
          {!editable && candidate.status === "confirmed" ? <p className="f4-inline-success"><CheckCircle2 size={16} />该候选已经确认。若要改变安排，请先在内部日历撤销。</p> : null}
          {!editable && candidate.status === "rejected" ? <p className="f4-inline-warning"><AlertTriangle size={16} />已拒绝，且没有产生内部日历事件。</p> : null}
        </section>

        <aside className="f4-card f4-ledger-card">
          <div className="f4-card-head"><div><p className="eyebrow">写入账本</p><h2>确认前后可核对</h2></div></div>
          <div className="f4-ledger-count"><strong>{calendar.isPending ? "—" : calendar.data?.length ?? 0}</strong><span>条内部日历历史</span></div>
          <ul>
            <li><CheckCircle2 size={16} /><span><strong>候选已生成</strong>仍可修改或拒绝</span></li>
            <li className={preview ? "active" : ""}><ShieldCheck size={16} /><span><strong>影响已预览</strong>{preview ? "等待你一次性确认" : "目前零写入"}</span></li>
            <li className={hasEvent ? "active" : ""}><CalendarCheck2 size={16} /><span><strong>内部事件</strong>{hasEvent ? "历史已保留" : "尚未创建"}</span></li>
          </ul>
          {hasEvent ? <Link className="button button-secondary" href={`/courses/${courseId}/calendar`}>打开内部日历 <ArrowRight size={16} /></Link> : null}
        </aside>
      </div>

      <section className="f4-action-log">
        <div><p className="eyebrow">追加式行动记录</p><h2>开始、跳过不会覆盖旧状态</h2></div>
        <div className="cluster"><button className="button button-secondary" onClick={() => actionEvent.mutate("started")}><Play size={15} />记录开始</button><button className="button button-secondary" onClick={() => actionEvent.mutate("skipped")}><SkipForward size={15} />记录跳过</button></div>
      </section>

      <details className="f4-diagnostics">
        <summary>异常保护验证{isContractMock ? "（仅合同 Mock）" : ""}</summary>
        <p>以下按钮会故意发送错误版本或过期令牌。预期结果都是“被服务拒绝”，日历条数不增加。</p>
        <div className="cluster"><button className="button button-secondary" onClick={() => simulate("conflict")}>模拟版本冲突</button><button className="button button-secondary" onClick={() => simulate("expired")}>模拟确认过期</button></div>
      </details>

      {preview ? <ConfirmationDialog preview={preview} busy={confirm.isPending} onClose={closePreview} onConfirm={() => confirm.mutate()} returnFocusRef={confirmationTriggerRef} /> : null}
    </F4Shell>
  );
}
