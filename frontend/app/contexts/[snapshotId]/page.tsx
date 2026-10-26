"use client";

import { ArrowLeft, ArrowRight, CheckCircle2, FileStack, Link2, ShieldAlert } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AppShell, StepStrip } from "@/components/AppShell";
import { LoadingCard, Notice } from "@/components/Feedback";
import { StatusChip } from "@/components/StatusChip";
import { contextSnapshotSchema } from "@/features/materials/schema";
import { AppError, apiFetchContract, presentError } from "@/lib/api/client";
import type { ContextSnapshot } from "@/lib/api/types";

export default function SnapshotPage() {
  const { snapshotId } = useParams<{ snapshotId: string }>();
  const router = useRouter();
  const [snapshot, setSnapshot] = useState<ContextSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<{ message: string; detail?: string } | null>(null);

  const load = useCallback(async () => {
    try { setSnapshot(await apiFetchContract(contextSnapshotSchema, `/api/v1/context-snapshots/${snapshotId}`)); setError(null); }
    catch (caught) {
      if (caught instanceof AppError && caught.status === 401) router.replace(`/login?next=${encodeURIComponent(`/contexts/${snapshotId}`)}`);
      else setError(presentError(caught));
    } finally { setLoading(false); }
  }, [router, snapshotId]);

  useEffect(() => { void load(); }, [load]);

  if (loading) return <AppShell><main className="page-wrap"><LoadingCard label="正在读取不可变上下文快照…" /></main></AppShell>;
  if (!snapshot) return <AppShell><main className="page-narrow">{error ? <Notice tone="error" {...error} /> : null}</main></AppShell>;
  const ready = snapshot.status === "ready";
  const coverageTone = snapshot.coverage_status === "complete" ? "success" : snapshot.coverage_status === "blocked" ? "danger" : "warning";

  return (
    <AppShell><main className="page-wrap">
      <StepStrip active={3} />
      <div className="page-head"><div className="page-head-copy"><p className="eyebrow">材料确认结果</p><h1>{ready ? "材料已切块并完成向量索引" : "材料范围需要调整"}</h1><p className="lede">系统冻结了材料版本、切块位置和 Embedding 模型，后续笔记与答疑都能回到同一份原文依据。</p></div><div className="cluster">{ready ? <Link className="button button-primary" href={`/courses/${snapshot.course_id}/workspace`}>进入学习台 <ArrowRight size={17} /></Link> : null}<Link className="button button-secondary" href={`/courses/${snapshot.course_id}/context`}><ArrowLeft size={17} />重新选择</Link></div></div>
      {error ? <div style={{ marginBottom: 18 }}><Notice tone="error" {...error} /></div> : null}
      <div style={{ marginBottom: 18 }}>{ready ? <Notice tone="success" message="RAG 预处理完成，可以生成结构化笔记。" detail={`已建立 ${snapshot.indexed_chunk_count} 个可复用检索块；点击“进入学习台”继续。`} /> : <Notice tone="error" message="材料内容超出本次安全处理范围。" detail="返回后重新选择较少的材料，系统不会擅自丢掉内容。" />}</div>
      <section className="card">
        <div className="card-head"><div><p className="eyebrow">覆盖与规模</p><h2>后端计算结果</h2></div><StatusChip label={snapshot.coverage_status === "complete" ? "完整覆盖" : snapshot.coverage_status === "blocked" ? "已阻止" : "已分段"} tone={coverageTone} /></div>
        <div className="stat-grid"><div className="stat"><div className="stat-value">{snapshot.materials.length}</div><div className="stat-label">材料版本</div></div><div className="stat"><div className="stat-value">{snapshot.indexed_chunk_count}</div><div className="stat-label">检索切块</div></div><div className="stat"><div className="stat-value">{snapshot.token_estimate.toLocaleString()}</div><div className="stat-label">估算 Token</div></div></div>
        <div className="divider" />
        <div className="grid-two"><div className="subtle-card"><h3>上下文策略</h3><p className="mono small" style={{ marginBottom: 0 }}>{snapshot.context_mode} · {snapshot.policy_version}</p></div><div className="subtle-card"><h3>Embedding 索引</h3><p className="mono small" style={{ marginBottom: 0 }}>{snapshot.index_status} · {snapshot.embedding_provider} · {snapshot.embedding_model_id} · {snapshot.retrieval_config_version}</p></div></div>
      </section>
      <section className="card"><div className="card-head"><div><p className="eyebrow">材料版本</p><h2>按选择顺序进入上下文</h2></div><FileStack size={21} /></div><div className="stack">{snapshot.materials.map((material, index) => <div className="source-link" key={material.material_id}><span><strong>{index + 1}. {material.display_name}</strong><br /><span className="small muted mono">版本 {material.parse_version_id}</span></span><CheckCircle2 size={18} color="var(--success)" /></div>)}</div></section>
      <section className="card"><div className="card-head"><div><p className="eyebrow">来源追溯</p><h2>逐条核对 AI 能看到的原文</h2><p className="muted">来源链接仍会验证当前登录人是否有权限。</p></div><Link2 size={21} /></div>{snapshot.source_ref_ids.length ? <div className="source-list">{snapshot.source_ref_ids.map((id, index) => <Link className="source-link" href={`/sources/${id}`} key={id}><span><strong>来源 {index + 1}</strong><br /><span className="small muted mono">{id}</span></span><ArrowRight size={16} /></Link>)}</div> : <div className="notice notice-error"><ShieldAlert size={18} /><p>快照没有来源引用，不能作为有效交付。</p></div>}</section>
      {snapshot.segment_plan.length ? <section className="card"><details><summary style={{ cursor: "pointer", fontWeight: 760 }}>查看后端分段计划（验证信息）</summary><pre className="mono small" style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", marginBottom: 0 }}>{JSON.stringify(snapshot.segment_plan, null, 2)}</pre></details></section> : null}
    </main></AppShell>
  );
}
