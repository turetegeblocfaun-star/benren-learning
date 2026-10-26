"use client";

import { BookCheck, CalendarClock, CheckCircle2, Gauge, ShieldQuestion } from "lucide-react";
import { useParams } from "next/navigation";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Notice } from "@/components/Feedback";
import { F5Shell, F5Status } from "@/components/controlled/F5Shell";
import { adaptiveReviewSchema, subjectiveAssessmentSchema, subjectiveExerciseListSchema, subjectiveExerciseSchema, type SubjectiveAssessment, type SubjectiveExercise } from "@/features/controlled/schema";
import { learningAssetListSchema } from "@/features/system/schema";
import { apiFetchContract, jsonBody, presentError } from "@/lib/api/client";
import { isContractMock } from "@/lib/runtime";

export default function ControlledPracticePage() {
  const { courseId } = useParams<{ courseId: string }>();
  const client = useQueryClient();
  const [exercise, setExercise] = useState<SubjectiveExercise | null>(null);
  const [assessment, setAssessment] = useState<SubjectiveAssessment | null>(null);
  const [answer, setAnswer] = useState(""); const [reflection, setReflection] = useState("");
  const [ratings, setRatings] = useState<Record<string, number>>({ concept: 3, evidence: 3 });
  const adaptive = useQuery({ queryKey: ["f5-adaptive", courseId], queryFn: () => apiFetchContract(adaptiveReviewSchema, `/api/v1/courses/${courseId}/adaptive-review`) });
  const assets = useQuery({ queryKey: ["learning-assets", courseId], queryFn: () => apiFetchContract(learningAssetListSchema, `/api/v1/courses/${courseId}/learning-assets?limit=100`) });
  const exercises = useQuery({ queryKey: ["subjective-exercises", courseId], queryFn: () => apiFetchContract(subjectiveExerciseListSchema, `/api/v1/courses/${courseId}/subjective-exercises?limit=100`) });
  const activeExercise = exercise ?? exercises.data?.[0] ?? null;
  const contextSnapshotId = assets.data?.find((item) => item.asset_type === "note" && item.status !== "failed")?.context_snapshot_id ?? assets.data?.find((item) => item.status !== "failed")?.context_snapshot_id ?? (isContractMock ? "snapshot-f5" : undefined);
  const generate = useMutation({ mutationFn: () => {
    if (!contextSnapshotId) throw new Error("请先生成结构化笔记，再创建主观练习");
    return apiFetchContract(subjectiveExerciseSchema, `/api/v1/courses/${courseId}/subjective-exercises`, { method: "POST", body: jsonBody({ context_snapshot_id: contextSnapshotId, focus: "解释本课程的核心概念" }) });
  }, onSuccess: async (value) => { setExercise(value); await client.invalidateQueries({ queryKey: ["subjective-exercises", courseId] }); } });
  const assess = useMutation({
    mutationFn: () => apiFetchContract(subjectiveAssessmentSchema, `/api/v1/subjective-exercises/${activeExercise?.id}/assessments`, { method: "POST", body: jsonBody({ response_text: answer, rubric_ratings: activeExercise?.rubric.map((item) => ({ criterion_id: item.id, rating: ratings[item.id] ?? 3, evidence_note: `我按“${item.label}”检查了自己的回答。` })), reflection, confidence: 4 }) }),
    onSuccess: async (value) => { setAssessment(value); await client.invalidateQueries({ queryKey: ["f5-adaptive", courseId] }); },
  });
  const error = generate.error ?? assess.error;
  return <F5Shell eyebrow="F5 · P1 学习能力" title="主观题由你自评，不由模型裁决" description="题目和 Rubric 来自材料；你提交回答、证据、自评分与反思。系统不返回自动正确或错误，只把真实历史用于解释下一次复习间隔。" gate="practice" backHref="/controlled">
    <div className="f5-two-grid">
      <section className="f5-panel">
        <div className="f5-panel-head"><div><p className="eyebrow">主观练习</p><h2>解释，而不是猜选项</h2></div>{activeExercise ? <F5Status value={activeExercise.status} /> : <ShieldQuestion size={23} />}</div>
        {!activeExercise ? <div className="f5-empty"><BookCheck size={26} /><p>{contextSnapshotId ? "还没有主观练习，可以基于已恢复的笔记上下文生成一题。" : "请先在学习台生成结构化笔记，系统才能建立可追溯的主观练习上下文。"}</p><button className="button button-primary" onClick={() => generate.mutate()} disabled={generate.isPending || !contextSnapshotId}>{generate.isPending ? "生成中…" : "生成主观练习"}</button></div> : <>
          <div className="f5-prompt"><small>题目 · 来源可追溯</small><h3>{activeExercise.prompt}</h3><span>来源：{activeExercise.source_ref_ids.join("、")}</span></div>
          <label className="field"><span>我的回答</span><textarea className="input f5-textarea" value={answer} onChange={(e) => setAnswer(e.target.value)} placeholder="用自己的话解释，不需要迎合标准答案。" /></label>
          <div className="f5-rubric">{activeExercise.rubric.map((item) => <article key={item.id}><div><strong>{item.label}</strong><p>{item.description}</p></div><label><span>自评 {ratings[item.id] ?? 3}/5</span><input aria-label={`${item.label}自评分`} type="range" min="1" max="5" value={ratings[item.id] ?? 3} onChange={(e) => setRatings((old) => ({ ...old, [item.id]: Number(e.target.value) }))} /></label></article>)}</div>
          <label className="field"><span>反思与下一步</span><textarea className="input" value={reflection} onChange={(e) => setReflection(e.target.value)} placeholder="还有哪里说得不够清楚？" /></label>
          <button className="button button-primary" onClick={() => assess.mutate()} disabled={assess.isPending || answer.trim().length < 4 || reflection.trim().length < 2}>{assess.isPending ? "保存中…" : "提交自评与反思"}</button>
        </>}
        {error ? <Notice tone="error" {...presentError(error)} /> : null}
        {assessment ? <div className="f5-no-grade"><CheckCircle2 size={19} /><div><strong>自评已记录，没有自动判定对错</strong><p>`automatic_correctness = null` · 置信度 {assessment.confidence}/5</p></div></div> : null}
      </section>
      <section className="f5-panel">
        <div className="f5-panel-head"><div><p className="eyebrow">自适应复习</p><h2>间隔必须说得出依据</h2></div><Gauge size={23} /></div>
        {adaptive.isPending ? <div className="f5-empty">正在读取真实作答历史…</div> : adaptive.error ? <Notice tone="error" {...presentError(adaptive.error)} /> : adaptive.data ? <>
          <div className="f5-interval"><CalendarClock size={24} /><strong>{adaptive.data.interval_days}</strong><span>天后复习</span></div><p className="f5-explanation">{adaptive.data.explanation}</p>
          <dl className="f5-evidence">{Object.entries(adaptive.data.evidence).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value === null ? "暂无" : String(value)}</dd></div>)}</dl><small>算法版本：{adaptive.data.algorithm_version}</small>
        </> : null}
      </section>
    </div>
  </F5Shell>;
}
