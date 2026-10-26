"use client";

import { ArrowRight, CheckCircle2, CircleHelp, Link2, ListTree, RefreshCw, Share2 } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { LoadingCard, Notice } from "@/components/Feedback";
import { F3Shell, VersionBanner } from "@/components/learning/F3Shell";
import { graphContentSchema, learningAssetSchema, type LearningAsset } from "@/features/learning/schema";
import { learningAssetListSchema, quizListSchema } from "@/features/system/schema";
import { apiFetchContract, presentError } from "@/lib/api/client";

const mastery = {
  unassessed: ["未检验", "neutral"],
  learning: ["学习中", "running"],
  mastered: ["已掌握", "success"],
  needs_review: ["需复习", "warning"],
} as const;

export default function GraphPage() {
  const { courseId, assetId } = useParams<{ courseId: string; assetId: string }>();
  const [view, setView] = useState<"graph" | "list">("graph");
  const asset = useQuery({
    queryKey: ["learning-asset", assetId],
    queryFn: () => apiFetchContract(learningAssetSchema, `/api/v1/learning-assets/${assetId}`),
    refetchInterval: (query) => {
      const data = query.state.data as LearningAsset | undefined;
      return data && !data.current_version && !["failed", "cancelled"].includes(data.status) ? 750 : false;
    },
  });
  const assets = useQuery({ queryKey: ["learning-assets", courseId], queryFn: () => apiFetchContract(learningAssetListSchema, `/api/v1/courses/${courseId}/learning-assets?limit=100`) });
  const quizzes = useQuery({ queryKey: ["quizzes", courseId], queryFn: () => apiFetchContract(quizListSchema, `/api/v1/courses/${courseId}/quizzes?limit=100`) });
  const noteId = assets.data?.find((item) => item.asset_type === "note" && item.status !== "failed")?.id;
  const quizId = quizzes.data?.find((item) => item.status !== "failed")?.id;
  const content = asset.data?.current_version ? graphContentSchema.safeParse(asset.data.current_version.content) : null;

  if (asset.isPending || (asset.data && !asset.data.current_version && !["failed", "cancelled"].includes(asset.data.status))) return <F3Shell eyebrow="知识图谱" title="正在读取概念关系" description="图谱不可用时仍会提供等价概念列表。"><LoadingCard label="DeepSeek 正在生成知识图谱，页面会自动更新…" /></F3Shell>;
  if (asset.error) return <F3Shell eyebrow="知识图谱" title="图谱没有成功打开" description="可返回笔记重新生成。"><Notice tone="error" {...presentError(asset.error)} /></F3Shell>;
  if (asset.data?.status === "failed") return <F3Shell eyebrow="知识图谱" title="图谱生成失败" description="笔记和上下文仍然保留。"><Notice tone="error" message={asset.data.error_message ?? "图谱生成没有成功，请返回笔记页重试。"} /></F3Shell>;
  if (!asset.data?.current_version || !content?.success) return <F3Shell eyebrow="知识图谱" title="图谱结构需要恢复" description="当前版本无法安全渲染。"><Notice tone="error" message="图谱合同校验失败，已自动阻止空白画布。" /></F3Shell>;
  const stale = asset.data.status === "stale";
  const graphNodes = content.data.nodes.slice(0, 12).map((node, index) => ({ ...node, renderId: `${node.id}-${index}` }));
  const positions = new Map(graphNodes.map((node, index) => {
    const angle = (Math.PI * 2 * index) / Math.max(graphNodes.length, 1) - Math.PI / 2;
    return [node.renderId, { x: 50 + Math.cos(angle) * 38, y: 50 + Math.sin(angle) * 36 }];
  }));
  const firstRenderId = new Map(graphNodes.map((node) => [node.id, node.renderId]));
  const graphEdges = content.data.edges.map((edge) => ({ ...edge, fromRenderId: firstRenderId.get(edge.from), toRenderId: firstRenderId.get(edge.to) })).filter((edge) => edge.fromRenderId && edge.toRenderId);
  const graphTitle = graphNodes.length
    ? `${graphNodes.slice(0, 2).map((node) => node.label).join("与")}的概念地图`
    : "课程概念地图";

  return (
    <F3Shell
      eyebrow="知识图谱 · 概念与关系"
      title={graphTitle}
      description="图形和列表是同一份数据。来源、掌握态和版本都不依赖颜色才能识别。"
      backHref={noteId ? `/courses/${courseId}/notes/${noteId}` : `/courses/${courseId}/workspace`}
      actions={<div className="f3-view-switch" role="group" aria-label="图谱显示方式"><button aria-pressed={view === "graph"} onClick={() => setView("graph")}><Share2 size={15} />图谱</button><button aria-pressed={view === "list"} onClick={() => setView("list")}><ListTree size={15} />概念列表</button></div>}
    >
      <VersionBanner version={asset.data.current_version.version_no} stale={stale} />
      {stale ? <div style={{ marginTop: 14 }}><Notice tone="info" message="笔记已经产生新版本，这张图谱仍保留旧结果但不再作为当前依据。" detail="返回笔记页，用当前版本重新生成即可恢复。" /></div> : null}

      <section className="card f3-graph-card">
        {view === "graph" ? (
          <div className="f3-graph-canvas" role="img" aria-label={`${graphNodes.map((node) => node.label).join("、")}的关系图`}>
            <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
              <defs><marker id="arrow-f3" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" /></marker></defs>
              {graphEdges.map((edge, index) => {
                const from = positions.get(edge.fromRenderId!)!;
                const to = positions.get(edge.toRenderId!)!;
                return <line x1={from.x} y1={from.y} x2={to.x} y2={to.y} key={`${edge.from}-${edge.to}-${index}`} />;
              })}
            </svg>
            {graphNodes.map((node) => {
              const [label] = mastery[node.mastery_state];
              const position = positions.get(node.renderId)!;
              return <div className="f3-node f3-node-live" style={{ left: `${position.x}%`, top: `${position.y}%` }} key={node.renderId}><small>{label}</small><strong>{node.label}</strong></div>;
            })}
            {content.data.nodes.length > graphNodes.length ? <p className="f3-graph-overflow">图形展示前 12 个概念；切换“概念列表”查看全部 {content.data.nodes.length} 个。</p> : null}
          </div>
        ) : (
          <div className="f3-concept-list">
            {content.data.nodes.map((node) => {
              const [label, tone] = mastery[node.mastery_state];
              return <article key={`${node.id}-${node.label}`}><div><span className={`status-chip tone-${tone}`}>{label}</span><h2>{node.label}</h2></div><div className="cluster">{node.source_ref_ids.map((id) => <Link className="f3-source-link" href={`/sources/${id}`} key={id}><Link2 size={14} />课堂来源</Link>)}</div></article>;
            })}
            <div className="f3-edge-list"><h3>关系清单</h3>{content.data.edges.map((edge, index) => <p key={`${edge.from}-${edge.to}-${index}`}><strong>{content.data.nodes.find((node) => node.id === edge.from)?.label}</strong><ArrowRight size={14} /><span>{edge.label}</span><ArrowRight size={14} /><strong>{content.data.nodes.find((node) => node.id === edge.to)?.label}</strong></p>)}</div>
          </div>
        )}
      </section>

      <div className="grid-two f3-graph-foot">
        <section className="subtle-card"><div className="cluster"><CheckCircle2 size={18} /><h3>掌握态来自练习证据</h3></div><p className="small muted">未作答时保持“未检验”，不会用模型猜测掌握程度。</p></section>
        <section className="subtle-card"><div className="cluster"><CircleHelp size={18} /><h3>图谱失败也能学习</h3></div><p className="small muted">切换“概念列表”可访问同样的节点、关系、状态和来源。</p></section>
      </div>
      <div className="f3-footer-action">{stale && noteId ? <Link className="button button-primary" href={`/courses/${courseId}/notes/${noteId}`}><RefreshCw size={16} />返回当前笔记版本</Link> : quizId ? <Link className="button button-primary" href={`/courses/${courseId}/quizzes/${quizId}`}>用一道题检验当前概念 <ArrowRight size={16} /></Link> : <Link className="button button-secondary" href={`/courses/${courseId}/workspace`}>返回学习台</Link>}</div>
    </F3Shell>
  );
}
