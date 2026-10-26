"use client";

import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Layers3, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AppShell, StepStrip } from "@/components/AppShell";
import { EmptyState, LoadingCard, Notice } from "@/components/Feedback";
import { contextSnapshotSchema, courseSchema, materialListSchema } from "@/features/materials/schema";
import { AppError, apiFetchContract, idempotencyKey, jsonBody, presentError } from "@/lib/api/client";
import type { Course, Material } from "@/lib/api/types";
import { materialTypeLabel } from "@/lib/status";

export default function ContextBuilderPage() {
  const { courseId } = useParams<{ courseId: string }>();
  const router = useRouter();
  const [course, setCourse] = useState<Course | null>(null);
  const [usable, setUsable] = useState<Material[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ message: string; detail?: string } | null>(null);

  const load = useCallback(async () => {
    try {
      const [nextCourse, response] = await Promise.all([
        apiFetchContract(courseSchema, `/api/v1/courses/${courseId}`),
        apiFetchContract(materialListSchema, `/api/v1/courses/${courseId}/materials?status=usable`),
      ]);
      const items = response.items.filter((material) => material.active_parse_version_id);
      setCourse(nextCourse); setUsable(items); setSelected(items.map((item) => item.id));
    } catch (caught) {
      if (caught instanceof AppError && caught.status === 401) router.replace(`/login?next=${encodeURIComponent(`/courses/${courseId}/context`)}`);
      else setError(presentError(caught));
    } finally { setLoading(false); }
  }, [courseId, router]);

  useEffect(() => { void load(); }, [load]);

  function toggle(id: string) {
    setSelected((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  }

  function move(id: string, direction: -1 | 1) {
    setSelected((current) => {
      const index = current.indexOf(id); const target = index + direction;
      if (index < 0 || target < 0 || target >= current.length) return current;
      const next = [...current]; [next[index], next[target]] = [next[target], next[index]]; return next;
    });
  }

  async function createSnapshot() {
    if (!selected.length) return;
    setBusy(true); setError(null);
    const byId = new Map(usable.map((material) => [material.id, material]));
    try {
      const snapshot = await apiFetchContract(contextSnapshotSchema, `/api/v1/courses/${courseId}/context-snapshots`, {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey("snapshot") },
        body: jsonBody({
          task_type: "stage1_validation",
          selected_materials: selected.map((id, index) => ({ id, parse_version: byId.get(id)?.active_parse_version_id, selected_order: index })),
        }),
      });
      router.push(`/contexts/${snapshot.id}`);
    } catch (caught) { setError(presentError(caught)); setBusy(false); }
  }

  if (loading) return <AppShell><main className="page-wrap"><LoadingCard label="正在读取可用材料…" /></main></AppShell>;

  return (
    <AppShell><main className="page-wrap">
      <StepStrip active={3} />
      <div className="page-head"><div className="page-head-copy"><p className="eyebrow">混合上下文</p><h1>决定这一轮 AI 能看到什么</h1><p className="lede">只会使用你勾选的可用版本，并按这里的顺序生成不可变快照。来源位置会一起保留。</p></div><Link className="button button-secondary" href={`/courses/${courseId}/materials`}><ArrowLeft size={17} />返回材料页</Link></div>
      {error ? <div style={{ marginBottom: 18 }}><Notice tone="error" {...error} /></div> : null}
      <div className="grid-two" style={{ alignItems: "start" }}>
        <section className="card" style={{ marginTop: 0 }}><div className="card-head"><div><p className="eyebrow">选择</p><h2>{course?.title ?? "本课程"}的可用材料</h2><p className="muted">待校正或失败材料不会出现在这里。</p></div><button className="button button-ghost button-small" onClick={() => setSelected(selected.length === usable.length ? [] : usable.map((item) => item.id))}>{selected.length === usable.length ? "取消全选" : "全部选择"}</button></div>
          {!usable.length ? <EmptyState title="还没有可用材料" text="返回材料页，等待识别完成并处理所有待校正内容。" /> : <div className="stack">{usable.map((material) => { const order = selected.indexOf(material.id); return <div className="check-row" key={material.id}><input type="checkbox" checked={order >= 0} onChange={() => toggle(material.id)} aria-label={`选择 ${material.display_name}`} /><label onClick={() => toggle(material.id)} style={{ cursor: "pointer" }}><strong>{material.display_name}</strong><br /><span className="small muted">{materialTypeLabel(material.declared_type)} · 解析版本已锁定</span></label>{order >= 0 ? <span className="order-badge">{order + 1}</span> : null}</div>; })}</div>}
        </section>
        <section className="card" style={{ marginTop: 0 }}><div className="card-head"><div><p className="eyebrow">顺序</p><h2>上下文编排预览</h2><p className="muted">上面的内容会先进入上下文。调整顺序不会修改原材料。</p></div><Layers3 size={22} /></div>
          {!selected.length ? <EmptyState title="尚未选择" text="至少选择一份可用材料才能创建快照。" /> : <div className="stack">{selected.map((id, index) => { const material = usable.find((item) => item.id === id); if (!material) return null; return <div className="source-link" key={id}><span><strong>{index + 1}. {material.display_name}</strong><br /><span className="small muted">{materialTypeLabel(material.declared_type)}</span></span><span className="cluster"><button className="button button-ghost icon-button button-small" aria-label={`上移 ${material.display_name}`} disabled={index === 0} onClick={() => move(id, -1)}><ArrowUp size={16} /></button><button className="button button-ghost icon-button button-small" aria-label={`下移 ${material.display_name}`} disabled={index === selected.length - 1} onClick={() => move(id, 1)}><ArrowDown size={16} /></button></span></div>; })}</div>}
          <div className="divider" /><div className="notice notice-info"><ShieldCheck size={18} /><p>当前策略是 <strong>indexed_full</strong>：先按来源边界切块并生成 Embedding 向量索引；短材料完整使用，超长 Tutor 自动进入混合检索。</p></div>
          <button className="button button-primary" style={{ width: "100%", marginTop: 18 }} onClick={() => void createSnapshot()} disabled={busy || !selected.length}>{busy ? "正在切块并生成向量索引…" : <>创建并验证上下文 <ArrowRight size={17} /></>}</button>
        </section>
      </div>
    </main></AppShell>
  );
}
