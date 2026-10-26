"use client";

import { ArrowRight, CalendarClock, CheckCircle2, Clock3, FileCheck2, NotebookPen, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { LoadingCard, Notice } from "@/components/Feedback";
import { F4Shell } from "@/components/planning/F4Shell";
import { learningAssetTaskSchema } from "@/features/learning/schema";
import { contextSnapshotSchema, materialListSchema } from "@/features/materials/schema";
import { planningWorkspaceSchema, reviewPlanTaskSchema } from "@/features/planning/schema";
import { learningAssetListSchema } from "@/features/system/schema";
import { apiFetchContract, idempotencyKey, jsonBody, presentError } from "@/lib/api/client";

export function F4Workspace({ courseId }: { courseId: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const workspace = useQuery({ queryKey: ["f4-workspace", courseId], queryFn: () => apiFetchContract(planningWorkspaceSchema, `/api/v1/courses/${courseId}/workspace`) });
  const materials = useQuery({ queryKey: ["materials", courseId, "usable"], queryFn: () => apiFetchContract(materialListSchema, `/api/v1/courses/${courseId}/materials?status=usable`) });
  const assets = useQuery({ queryKey: ["learning-assets", courseId], queryFn: () => apiFetchContract(learningAssetListSchema, `/api/v1/courses/${courseId}/learning-assets?limit=100`) });
  const createPlan = useMutation({
    mutationFn: () => apiFetchContract(reviewPlanTaskSchema, `/api/v1/courses/${courseId}/review-plans`, {
      method: "POST", headers: { "Idempotency-Key": idempotencyKey("review-plan") },
      body: jsonBody({ timezone: "Asia/Shanghai", time_expression: "明晚学习 30 分钟" }),
    }),
    onSuccess: async ({ plan }) => {
      await queryClient.invalidateQueries({ queryKey: ["f4-workspace", courseId] });
      router.push(`/courses/${courseId}/plans/${plan.id}`);
    },
  });
  const generateNote = useMutation({
    mutationFn: async () => {
      const selected = materials.data?.items.filter((item) => item.active_parse_version_id) ?? [];
      if (!selected.length) throw new Error("没有可用于生成笔记的材料版本");
      const snapshot = await apiFetchContract(contextSnapshotSchema, `/api/v1/courses/${courseId}/context-snapshots`, {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey("note-context") },
        body: jsonBody({ task_type: "notes", selected_materials: selected.map((item, selected_order) => ({ id: item.id, parse_version: item.active_parse_version_id, selected_order })) }),
      });
      return apiFetchContract(learningAssetTaskSchema, `/api/v1/courses/${courseId}/learning-assets/notes`, {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey("note") },
        body: jsonBody({ context_snapshot_id: snapshot.id, locale: "zh-CN" }),
      });
    },
    onSuccess: ({ asset }) => router.push(`/courses/${courseId}/notes/${asset.id}`),
  });

  const existingPlan = workspace.data?.action.plan_id;
  const note = assets.data?.find((item) => item.asset_type === "note" && item.status !== "failed");
  return (
    <F4Shell eyebrow="F4 · 计划闭环" title="现在，只做一个明确的下一步" description="计划不会替你做决定。系统只给出一个有理由、有时长、可修改的建议，直到你确认前都不会写入日历。">
      {workspace.isPending ? <LoadingCard label="正在根据已确认材料计算唯一下一步…" /> : workspace.error ? <Notice tone="error" {...presentError(workspace.error)} /> : workspace.data ? (
        <section className="f4-next-card" aria-labelledby="f4-next-title">
          <div className="f4-next-index">01</div>
          <div>
            <div className="cluster f4-next-kicker"><span>唯一下一步</span><span>由 {workspace.data.derived_by === "workflow" ? "工作流" : "规则"} 决定</span></div>
            <h2 id="f4-next-title">{existingPlan ? "查看并确认下一次复习时间" : "生成下一次复习计划"}</h2>
            <p>{workspace.data.action.reason}</p>
            <div className="cluster f4-next-meta"><span><Clock3 size={15} />约 {workspace.data.action.duration_min} 分钟</span><span><ShieldCheck size={15} />确认前零写入</span></div>
          </div>
          {existingPlan ? (
            <Link className="button button-primary" href={`/courses/${courseId}/plans/${existingPlan}`}>查看待确认计划 <ArrowRight size={18} /></Link>
          ) : (
            <button className="button button-primary" onClick={() => createPlan.mutate()} disabled={createPlan.isPending}>{createPlan.isPending ? "正在生成候选时间…" : <>生成可确认计划 <ArrowRight size={18} /></>}</button>
          )}
        </section>
      ) : null}
      {createPlan.error ? <div style={{ marginTop: 16 }}><Notice tone="error" {...presentError(createPlan.error)} /></div> : null}

      <section className="f4-section">
        <div className="f4-section-heading"><div><p className="eyebrow">学习工具</p><h2>结构化笔记入口</h2></div><p>复习计划不会再覆盖学习工具；你可以随时打开现有笔记或基于当前材料重新整理。</p></div>
        <div className="card">
          <div className="card-head"><div><h3>{note ? "现有笔记可以继续查看" : "当前还没有可用笔记"}</h3><p className="muted">重新整理会先完成材料切块和 Embedding 向量索引，再生成带来源的笔记。</p></div><NotebookPen size={24} /></div>
          <div className="cluster">
            {note ? <Link className="button button-secondary" href={`/courses/${courseId}/notes/${note.id}`}>打开现有结构化笔记 <ArrowRight size={17} /></Link> : null}
            <button className="button button-primary" onClick={() => generateNote.mutate()} disabled={generateNote.isPending || materials.isPending}>
              {generateNote.isPending ? "正在建立索引并整理…" : note ? "重新整理结构化笔记" : "整理结构化笔记"}
            </button>
          </div>
        </div>
      </section>
      {generateNote.error ? <div style={{ marginTop: 16 }}><Notice tone="error" {...presentError(generateNote.error)} /></div> : null}

      <section className="f4-section">
        <div className="f4-section-heading"><div><p className="eyebrow">计划边界</p><h2>建议、确认、执行，三步分开</h2></div><p>你可以先查看影响，也可以改时间或拒绝；没有明确确认，就没有日历事件。</p></div>
        <div className="f4-rule-grid">
          <article><CalendarClock size={21} /><span>01</span><h3>建议候选时间</h3><p>说明时区、时长、目标与推荐理由，时间始终可改。</p></article>
          <article><FileCheck2 size={21} /><span>02</span><h3>查看写入影响</h3><p>先说清内部日历与通知会发生什么，外部日历不会被写入。</p></article>
          <article><CheckCircle2 size={21} /><span>03</span><h3>一次性确认</h3><p>令牌过期、重复使用或版本变化都会被拒绝，不产生重复事件。</p></article>
        </div>
      </section>
      <section className="f4-fineprint"><span>合同端点：GET /courses/{`{courseId}`}/workspace</span><span>计划 ID 由后端创建并恢复</span><span>外部日历仍需受控授权</span></section>
    </F4Shell>
  );
}
