"use client";

import { ArrowLeft, FileText, LocateFixed } from "lucide-react";
import Image from "next/image";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { LoadingCard, Notice } from "@/components/Feedback";
import { sourceRefSchema } from "@/features/materials/schema";
import { AppError, apiFetchContract, presentError } from "@/lib/api/client";
import type { SourceRef } from "@/lib/api/types";
import { locatorLabel, materialTypeLabel } from "@/lib/status";

export default function SourcePage() {
  const { sourceRefId } = useParams<{ sourceRefId: string }>();
  const router = useRouter();
  const [source, setSource] = useState<SourceRef | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<{ message: string; detail?: string } | null>(null);

  const load = useCallback(async () => {
    try { setSource(await apiFetchContract(sourceRefSchema, `/api/v1/source-refs/${sourceRefId}`)); }
    catch (caught) {
      if (caught instanceof AppError && caught.status === 401) router.replace(`/login?next=${encodeURIComponent(`/sources/${sourceRefId}`)}`);
      else setError(presentError(caught));
    } finally { setLoading(false); }
  }, [router, sourceRefId]);

  useEffect(() => { void load(); }, [load]);

  if (loading) return <AppShell><main className="page-wrap"><LoadingCard label="正在验证来源权限并定位原文…" /></main></AppShell>;
  if (!source) return <AppShell><main className="page-narrow">{error ? <Notice tone="error" {...error} /> : null}</main></AppShell>;
  const isImage = ["board_image", "handwriting_image"].includes(source.material_type);

  return (
    <AppShell><main className="page-wrap">
      <div className="page-head"><div className="page-head-copy"><p className="eyebrow">来源追溯</p><h1>{source.display_name}</h1><p className="lede">{materialTypeLabel(source.material_type)} · {locatorLabel(source)} · 解析版本 <span className="mono">{source.material_version_id}</span></p></div><button className="button button-secondary" onClick={() => router.back()}><ArrowLeft size={17} />返回</button></div>
      {error ? <div style={{ marginBottom: 18 }}><Notice tone="error" {...error} /></div> : null}
      <div className="grid-two" style={{ alignItems: "start" }}>
        <section className="card" style={{ marginTop: 0 }}><div className="card-head"><div><p className="eyebrow">被使用的文字</p><h2>模型上下文中的原文片段</h2></div><LocateFixed size={21} /></div><blockquote className="source-quote">{source.text}</blockquote><div className="divider" /><div className="cluster small muted"><span>定位：{source.locator_type}</span>{source.confidence !== null ? <span>识别置信度：{Math.round(source.confidence * 100)}%</span> : <span>供应商未返回置信分</span>}</div></section>
        <section className="card" style={{ marginTop: 0 }}><div className="card-head"><div><p className="eyebrow">原件对照</p><h2>回到材料中的位置</h2></div></div>{isImage ? <><Image className="media-preview" src={source.preview_path} alt={`${source.display_name} 原图`} width={1200} height={900} unoptimized />{source.bbox ? <p className="small muted" style={{ marginTop: 10 }}>识别框（归一化坐标）：<span className="mono">{source.bbox.map((value) => value.toFixed(3)).join(", ")}</span></p> : null}</> : source.material_type === "audio" ? <><audio className="media-preview" controls preload="metadata" src={source.preview_path}>浏览器不支持音频播放。</audio><p className="small muted" style={{ marginTop: 10 }}>时间位置：{locatorLabel(source)}</p></> : <div className="empty-state"><div className="empty-icon"><FileText size={24} /></div><p>文本原件可在新窗口打开；页面不会把文件内容当作 HTML 执行。</p><a className="button button-secondary" href={source.preview_path} target="_blank" rel="noreferrer">打开文本原件</a></div>}</section>
      </div>
    </main></AppShell>
  );
}
