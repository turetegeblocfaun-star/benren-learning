"use client";

import { ArrowRight, BrainCircuit, GitBranch, Link2, MessageCircleQuestion, PencilLine, Save, X } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { LoadingCard, Notice } from "@/components/Feedback";
import { F3Shell, SourceBadge, VersionBanner } from "@/components/learning/F3Shell";
import { learningAssetSchema, learningAssetTaskSchema, noteContentSchema, providerNoteContentSchema, quizTaskSchema, tutorSessionSchema, type LearningAsset } from "@/features/learning/schema";
import { contextSnapshotSchema, materialListSchema } from "@/features/materials/schema";
import { quizListSchema, tutorSessionListSchema } from "@/features/system/schema";
import { apiFetchContract, idempotencyKey, jsonBody, presentError } from "@/lib/api/client";

export default function NotePage() {
  const { courseId, assetId } = useParams<{ courseId: string; assetId: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [draftTitle, setDraftTitle] = useState("");
  const [draftSummary, setDraftSummary] = useState("");
  const queryKey = useMemo(() => ["learning-asset", assetId], [assetId]);
  const asset = useQuery({
    queryKey,
    queryFn: () => apiFetchContract(learningAssetSchema, `/api/v1/learning-assets/${assetId}`),
    refetchInterval: (query) => {
      const data = query.state.data as LearningAsset | undefined;
      return data && !data.current_version && !["failed", "cancelled"].includes(data.status) ? 750 : false;
    },
  });
  const materials = useQuery({ queryKey: ["materials", courseId, "usable"], queryFn: () => apiFetchContract(materialListSchema, `/api/v1/courses/${courseId}/materials?status=usable`) });
  const quizzes = useQuery({ queryKey: ["quizzes", courseId], queryFn: () => apiFetchContract(quizListSchema, `/api/v1/courses/${courseId}/quizzes?limit=100`) });
  const tutorSessions = useQuery({ queryKey: ["tutor-sessions", courseId], queryFn: () => apiFetchContract(tutorSessionListSchema, `/api/v1/courses/${courseId}/tutor-sessions?limit=100`) });
  const note = asset.data?.current_version ? noteContentSchema.safeParse(asset.data.current_version.content) : null;
  const noteTitle = note?.success ? note.data.title : "";
  const noteSummary = note?.success ? note.data.summary : "";

  useEffect(() => {
    if (!editing && noteTitle) { setDraftTitle(noteTitle); setDraftSummary(noteSummary); }
  }, [editing, noteSummary, noteTitle]);

  const save = useMutation({
    mutationFn: async () => {
      if (!asset.data?.current_version || !note?.success) throw new Error("笔记尚未就绪");
      const providerContent = providerNoteContentSchema.safeParse(asset.data.current_version.content);
      const nextContent = providerContent.success ? {
        ...providerContent.data,
        title: draftTitle.trim(),
        sections: providerContent.data.sections.map((section, index) => index === 0 ? { ...section, summary: draftSummary.trim() } : section),
      } : { ...note.data, title: draftTitle.trim(), summary: draftSummary.trim() };
      return apiFetchContract(learningAssetSchema, `/api/v1/learning-assets/${assetId}`, {
        method: "PATCH",
        headers: { "If-Match": String(asset.data.version), "Idempotency-Key": idempotencyKey("edit-note") },
        body: jsonBody({ content: nextContent }),
      });
    },
    onSuccess: (data) => { queryClient.setQueryData(queryKey, data); setEditing(false); },
  });

  const graph = useMutation({
    mutationFn: async () => {
      if (!asset.data?.current_version) throw new Error("笔记版本不存在");
      const selected = materials.data?.items.filter((item) => item.active_parse_version_id) ?? [];
      if (!selected.length) throw new Error("没有可用于生成图谱的材料版本");
      const snapshot = await apiFetchContract(contextSnapshotSchema, `/api/v1/courses/${courseId}/context-snapshots`, {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey("graph-context") },
        body: jsonBody({ task_type: "graph", selected_materials: selected.map((item, selected_order) => ({ id: item.id, parse_version: item.active_parse_version_id, selected_order })) }),
      });
      return apiFetchContract(learningAssetTaskSchema, `/api/v1/courses/${courseId}/learning-assets/graphs`, {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey("graph") },
        body: jsonBody({ context_snapshot_id: snapshot.id, note_version_id: asset.data.current_version.id, max_nodes: 40, max_edges: 80 }),
      });
    },
    onSuccess: ({ asset: next }) => router.push(`/courses/${courseId}/graph/${next.id}`),
  });

  async function createSnapshot(taskType: "quiz" | "tutor") {
    const selected = materials.data?.items.filter((item) => item.active_parse_version_id) ?? [];
    if (!selected.length) throw new Error("没有可用于创建学习任务的材料版本");
    return apiFetchContract(contextSnapshotSchema, `/api/v1/courses/${courseId}/context-snapshots`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey(`${taskType}-context`) },
      body: jsonBody({ task_type: taskType, selected_materials: selected.map((item, selected_order) => ({ id: item.id, parse_version: item.active_parse_version_id, selected_order })) }),
    });
  }

  const generateQuiz = useMutation({
    mutationFn: async () => {
      const snapshot = await createSnapshot("quiz");
      return apiFetchContract(quizTaskSchema, `/api/v1/courses/${courseId}/quizzes`, {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey("quiz") },
        body: jsonBody({ context_snapshot_id: snapshot.id, difficulty: "medium", count: 3, question_types: ["single_choice", "true_false"] }),
      });
    },
    onSuccess: ({ quiz }) => router.push(`/courses/${courseId}/quizzes/${quiz.id}`),
  });

  const startTutor = useMutation({
    mutationFn: async () => {
      const snapshot = await createSnapshot("tutor");
      return apiFetchContract(tutorSessionSchema, `/api/v1/courses/${courseId}/tutor-sessions`, {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey("tutor-session") },
        body: jsonBody({ context_snapshot_id: snapshot.id, learning_goal: `理解${noteTitle || "本课程核心内容"}`, target_problem: null, target_answer_fingerprint: null }),
      });
    },
    onSuccess: (session) => router.push(`/courses/${courseId}/tutor/${session.id}`),
  });

  if (asset.isPending || (asset.data && !asset.data.current_version && !["failed", "cancelled"].includes(asset.data.status))) return <F3Shell eyebrow="结构化笔记" title="正在整理材料" description="正在读取冻结版本与来源。"><LoadingCard label="DeepSeek 正在生成结构化笔记，页面会自动更新…" /></F3Shell>;
  if (asset.error) return <F3Shell eyebrow="结构化笔记" title="笔记没有成功打开" description="输入会保留；可刷新后继续。"><Notice tone="error" {...presentError(asset.error)} /></F3Shell>;
  if (asset.data?.status === "failed") return <F3Shell eyebrow="结构化笔记" title="笔记生成失败" description="材料和已确认的范围仍然保留，可以直接返回重试。" backHref={`/courses/${courseId}/workspace`}><Notice tone="error" message={asset.data.error_message ?? "笔记生成没有成功，请返回学习台重试。"} detail="点击下方按钮返回，系统会使用当前可用材料重新生成。" /><div style={{ marginTop: 18 }}><Link className="button button-primary" href={`/courses/${courseId}/workspace`}>返回学习台重新生成 <ArrowRight size={16} /></Link></div></F3Shell>;
  if (!asset.data?.current_version || !note?.success) return <F3Shell eyebrow="结构化笔记" title="笔记结构需要恢复" description="服务已返回资产，但当前版本不能安全渲染。"><Notice tone="error" message="笔记合同校验失败，没有执行不安全的内容。" /></F3Shell>;

  return (
    <F3Shell
      eyebrow="结构化笔记 · 来源分层"
      title={editing ? "修订这份笔记" : note.data.title}
      description={editing ? "保存会创建新版本；来源、Prompt 版本和旧内容不会被覆盖。" : note.data.summary}
      backHref={`/courses/${courseId}/workspace`}
      actions={editing ? <><button className="button button-ghost" onClick={() => setEditing(false)}><X size={16} />取消</button><button className="button button-primary" disabled={!draftTitle.trim() || !draftSummary.trim() || save.isPending} onClick={() => save.mutate()}><Save size={16} />{save.isPending ? "保存中…" : "保存新版本"}</button></> : <button className="button button-secondary" onClick={() => setEditing(true)}><PencilLine size={16} />编辑笔记</button>}
    >
      <VersionBanner version={asset.data.current_version.version_no} message={asset.data.current_version.source_kind === "user_edit" ? "这是人工修订版本；旧版仍保留在后端版本链中。" : undefined} />
      {save.error ? <div style={{ marginTop: 14 }}><Notice tone="error" {...presentError(save.error)} /></div> : null}
      {editing ? (
        <section className="card f3-edit-card">
          <div className="field"><label htmlFor="note-title">笔记标题</label><input id="note-title" className="input" value={draftTitle} onChange={(event) => setDraftTitle(event.target.value)} /></div>
          <div className="field"><label htmlFor="note-summary">概要</label><textarea id="note-summary" className="textarea" value={draftSummary} onChange={(event) => setDraftSummary(event.target.value)} /></div>
          <p className="small muted">本次演示只编辑标题和概要；结构区块和来源引用会原样随新版本保存。</p>
        </section>
      ) : null}

      <div className="f3-note-layout">
        <article className="f3-note-paper">
          {note.data.sections.map((section, index) => (
            <section className="f3-note-section" key={section.id}>
              <div className="f3-note-index">{String(index + 1).padStart(2, "0")}</div>
              <div>
                <div className="cluster"><SourceBadge kind={section.provenance} /><h2>{section.title}</h2></div>
                <p>{section.body}</p>
                {section.source_ref_ids.length ? <div className="cluster">{section.source_ref_ids.map((id) => <Link className="f3-source-link" href={`/sources/${id}`} key={id}><Link2 size={14} />查看课堂来源</Link>)}</div> : <p className="small muted">此区块没有上传材料引用，已通过来源层级明确标识。</p>}
              </div>
            </section>
          ))}
        </article>
        <aside className="f3-note-aside">
          <p className="eyebrow">版本与依据</p>
          <dl className="f3-detail-list"><div><dt>资产版本</dt><dd>v{asset.data.current_version.version_no}</dd></div><div><dt>上下文</dt><dd>{asset.data.context_snapshot_id}</dd></div><div><dt>模型合同</dt><dd>{asset.data.current_version.requested_model_id}</dd></div><div><dt>来源数量</dt><dd>{asset.data.current_version.source_ref_ids.length}</dd></div></dl>
          <div className="stack" style={{ gap: 9 }}>
            <button className="button button-primary" style={{ width: "100%" }} onClick={() => graph.mutate()} disabled={graph.isPending || materials.isPending}>{graph.isPending ? "正在生成图谱…" : <>用当前版本生成图谱 <GitBranch size={16} /></>}</button>
            {quizzes.data?.[0] ? <Link className="button button-secondary" href={`/courses/${courseId}/quizzes/${quizzes.data[0].id}`}><BrainCircuit size={16} />打开已有测验</Link> : <button className="button button-secondary" onClick={() => generateQuiz.mutate()} disabled={generateQuiz.isPending || materials.isPending}><BrainCircuit size={16} />{generateQuiz.isPending ? "正在生成测验…" : "生成客观测验"}</button>}
            {tutorSessions.data?.[0] ? <Link className="button button-secondary" href={`/courses/${courseId}/tutor/${tutorSessions.data[0].id}`}><MessageCircleQuestion size={16} />打开已有 Tutor</Link> : <button className="button button-secondary" onClick={() => startTutor.mutate()} disabled={startTutor.isPending || materials.isPending}><MessageCircleQuestion size={16} />{startTutor.isPending ? "正在创建 Tutor…" : "开始引导式 Tutor"}</button>}
          </div>
          {graph.error || generateQuiz.error || startTutor.error ? <div style={{ marginTop: 12 }}><Notice tone="error" {...presentError(graph.error ?? generateQuiz.error ?? startTutor.error)} /></div> : null}
          <p className="small muted" style={{ marginTop: 12 }}>图谱会冻结当前笔记版本。之后再次修改笔记，旧图谱会明确显示 stale。</p>
        </aside>
      </div>
      {quizzes.data?.[0] ? <div className="f3-footer-action"><Link className="button button-secondary" href={`/courses/${courseId}/quizzes/${quizzes.data[0].id}`}>用测验检验理解 <ArrowRight size={16} /></Link></div> : null}
    </F3Shell>
  );
}
