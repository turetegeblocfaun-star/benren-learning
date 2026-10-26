"use client";

import { ArrowLeft, Check, FileText, Save } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { AppShell, StepStrip } from "@/components/AppShell";
import { LoadingCard, Notice } from "@/components/Feedback";
import { StatusChip } from "@/components/StatusChip";
import { materialSchema, materialVersionSchema } from "@/features/materials/schema";
import { AppError, apiFetchContract, idempotencyKey, jsonBody, presentError } from "@/lib/api/client";
import type { Material, MaterialVersion, Segment } from "@/lib/api/types";
import { locatorLabel, materialStatus, materialTypeLabel } from "@/lib/status";

type Correction = {
  segment_id: string;
  action: "replace" | "accept";
  text: string | null;
};

export default function ReviewMaterialPage() {
  const { materialId } = useParams<{ materialId: string }>();
  const router = useRouter();
  const [material, setMaterial] = useState<Material | null>(null);
  const [version, setVersion] = useState<MaterialVersion | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<{ message: string; detail?: string } | null>(null);
  const [success, setSuccess] = useState("");

  const load = useCallback(async () => {
    try {
      const nextMaterial = await apiFetchContract(materialSchema, `/api/v1/materials/${materialId}`);
      if (!nextMaterial.active_parse_version_id) throw new AppError("PARSE_PENDING", "这份材料还没有可查看的解析结果。");
      const nextVersion = await apiFetchContract(materialVersionSchema, `/api/v1/materials/${materialId}/versions/${nextMaterial.active_parse_version_id}`);
      setMaterial(nextMaterial); setVersion(nextVersion);
      setEdits(Object.fromEntries(nextVersion.segments.map((segment) => [segment.id, segment.text])));
      setError(null);
    } catch (caught) {
      if (caught instanceof AppError && caught.status === 401) router.replace(`/login?next=${encodeURIComponent(`/materials/${materialId}/review`)}`);
      else setError(presentError(caught));
    } finally { setLoading(false); }
  }, [materialId, router]);

  useEffect(() => { void load(); }, [load]);

  const corrections = useMemo<Correction[]>(() => {
    if (!version) return [];
    return version.segments.flatMap<Correction>((segment): Correction[] => {
      const text = edits[segment.id]?.trim() ?? "";
      if (text && text !== segment.text) return [{ segment_id: segment.id, action: "replace", text }];
      if (segment.review_required && !segment.review_accepted) return [{ segment_id: segment.id, action: "accept", text: null }];
      return [];
    });
  }, [edits, version]);

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!material || !corrections.length) { setSuccess("当前没有需要保存的修改。"); return; }
    setSaving(true); setError(null); setSuccess("");
    try {
      await apiFetchContract(materialVersionSchema, `/api/v1/materials/${material.id}/corrections`, {
        method: "PATCH",
        headers: { "Idempotency-Key": idempotencyKey("correct") },
        body: jsonBody({ expected_version: material.version, corrections }),
      });
      setSuccess("校正已保存为新版本，旧版本仍保留用于追溯。");
      await load();
    } catch (caught) { setError(presentError(caught)); }
    finally { setSaving(false); }
  }

  if (loading) return <AppShell><main className="page-wrap"><LoadingCard label="正在读取材料原件和解析版本…" /></main></AppShell>;
  if (!material || !version) return <AppShell><main className="page-narrow">{error ? <Notice tone="error" {...error} /> : null}</main></AppShell>;
  const status = materialStatus(material.status);
  const isImage = material.declared_type === "board_image" || material.declared_type === "handwriting_image";

  return (
    <AppShell><main className="page-wrap">
      <StepStrip active={2} />
      <div className="page-head"><div className="page-head-copy"><p className="eyebrow">材料核对</p><h1>{material.display_name}</h1><div className="cluster"><StatusChip {...status} /><span className="small muted">{materialTypeLabel(material.declared_type)} · 解析版本 {version.version_no} · {version.provider ?? version.parser}</span></div></div><Link className="button button-secondary" href={`/courses/${material.course_id}/materials`}><ArrowLeft size={17} />返回材料页</Link></div>
      {error ? <div style={{ marginBottom: 16 }}><Notice tone="error" {...error} /></div> : null}
      {success ? <div style={{ marginBottom: 16 }}><Notice tone="success" message={success} /></div> : null}
      <div className="grid-two" style={{ alignItems: "start" }}>
        <section className="card" style={{ marginTop: 0 }}><div className="card-head"><div><p className="eyebrow">原件</p><h2>对照原始材料</h2></div></div>
          {isImage ? <Image className="media-preview" src={`/api/v1/materials/${material.id}/original`} alt={`${material.display_name} 原图`} width={1200} height={900} unoptimized /> : material.declared_type === "audio" ? <audio className="media-preview" controls preload="metadata" src={`/api/v1/materials/${material.id}/original`}>浏览器不支持音频播放。</audio> : <div className="empty-state"><div className="empty-icon"><FileText size={24} /></div><p>文本原件不在页面中直接执行或渲染。</p><a className="button button-secondary" href={`/api/v1/materials/${material.id}/original`} target="_blank" rel="noreferrer">打开原件</a></div>}
          <div className="divider" /><p className="small muted">原件只用于对照。保存校正会创建新解析版本，不会覆盖原文件。</p>
        </section>
        <form className="card" style={{ marginTop: 0 }} onSubmit={save}>
          <div className="card-head"><div><p className="eyebrow">识别文字</p><h2>逐段确认或修改</h2><p className="muted">黄色提示代表置信度较低；不修改并保存即表示你接受该段。</p></div><span className="stage-pill">{version.segments.length} 段</span></div>
          <div className="segment-list">{version.segments.map((segment: Segment) => <div className="segment-card" key={segment.id}><div className="segment-head"><span>{locatorLabel(segment)}</span><span className={segment.review_required && !segment.review_accepted ? "confidence-low" : ""}>{segment.confidence === null ? "未提供置信分" : `置信度 ${Math.round(segment.confidence * 100)}%`}{segment.review_required && !segment.review_accepted ? " · 请确认" : ""}</span></div><label className="field"><span className="field-label">第 {segment.ordinal} 段文字</span><textarea className="textarea" style={{ minHeight: 112 }} value={edits[segment.id] ?? ""} onChange={(event) => setEdits((current) => ({ ...current, [segment.id]: event.target.value }))} /></label></div>)}</div>
          <div className="cluster" style={{ marginTop: 20 }}><button className="button button-primary" type="submit" disabled={saving}>{saving ? "正在保存版本…" : <><Save size={17} />保存校正</>}</button>{!corrections.length ? <span className="small muted"><Check size={15} style={{ verticalAlign: "middle" }} /> 已无待确认修改</span> : <span className="small muted">将保存 {corrections.length} 项变更/确认</span>}</div>
        </form>
      </div>
    </main></AppShell>
  );
}
