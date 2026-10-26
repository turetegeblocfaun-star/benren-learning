"use client";

import { ArrowLeft, BookOpenCheck, BrainCircuit, GitBranch, MessageCircleQuestion, NotebookPen } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";

import { AppShell } from "@/components/AppShell";
import { learningAssetListSchema, quizListSchema, tutorSessionListSchema } from "@/features/system/schema";
import { apiFetchContract } from "@/lib/api/client";
import { runtimeStatus } from "@/lib/runtime";

export function F3Shell({
  eyebrow,
  title,
  description,
  children,
  backHref,
  actions,
}: {
  eyebrow: string;
  title: string;
  description: string;
  children: ReactNode;
  backHref?: string;
  actions?: ReactNode;
}) {
  const { courseId } = useParams<{ courseId: string }>();
  const assets = useQuery({ queryKey: ["learning-assets", courseId], queryFn: () => apiFetchContract(learningAssetListSchema, `/api/v1/courses/${courseId}/learning-assets?limit=100`) });
  const quizzes = useQuery({ queryKey: ["quizzes", courseId], queryFn: () => apiFetchContract(quizListSchema, `/api/v1/courses/${courseId}/quizzes?limit=100`) });
  const tutorSessions = useQuery({ queryKey: ["tutor-sessions", courseId], queryFn: () => apiFetchContract(tutorSessionListSchema, `/api/v1/courses/${courseId}/tutor-sessions?limit=100`) });
  const note = assets.data?.find((item) => item.asset_type === "note" && item.status !== "failed");
  const graph = assets.data?.find((item) => item.asset_type === "graph" && item.status !== "failed");
  const quiz = quizzes.data?.find((item) => item.status !== "failed");
  const tutor = tutorSessions.data?.find((item) => item.status === "active") ?? tutorSessions.data?.[0];

  return (
    <AppShell>
      <main className="f3-page page-wrap">
        <div className="f3-preview-note" role="status">
          <span aria-hidden="true" /> {runtimeStatus.learning}
        </div>
        <nav className="f3-nav" aria-label="F3 学习闭环">
          <Link href={`/courses/${courseId}/workspace`}><BookOpenCheck size={16} />学习台</Link>
          {note ? <Link href={`/courses/${courseId}/notes/${note.id}`}><NotebookPen size={16} />结构笔记</Link> : <span><NotebookPen size={16} />暂无笔记</span>}
          {graph ? <Link href={`/courses/${courseId}/graph/${graph.id}`}><GitBranch size={16} />知识图谱</Link> : <span><GitBranch size={16} />暂无图谱</span>}
          {quiz ? <Link href={`/courses/${courseId}/quizzes/${quiz.id}`}><BrainCircuit size={16} />测验与错题</Link> : <span><BrainCircuit size={16} />暂无测验</span>}
          {tutor ? <Link href={`/courses/${courseId}/tutor/${tutor.id}`}><MessageCircleQuestion size={16} />Tutor</Link> : <span><MessageCircleQuestion size={16} />暂无 Tutor</span>}
        </nav>
        <div className="page-head f3-head">
          <div className="page-head-copy">
            <p className="eyebrow">{eyebrow}</p>
            <h1>{title}</h1>
            <p className="lede">{description}</p>
          </div>
          <div className="cluster">
            {backHref ? <Link className="button button-secondary" href={backHref}><ArrowLeft size={16} />返回</Link> : null}
            {actions}
          </div>
        </div>
        {children}
      </main>
    </AppShell>
  );
}

const sourceLabels = {
  uploaded_material: ["上传材料", "source-material"],
  material_example: ["材料案例", "source-example"],
  official_supplement: ["官方补充", "source-official"],
  ai_inference: ["AI 推断", "source-inference"],
  needs_review: ["待核对", "source-review"],
} as const;

export function SourceBadge({ kind }: { kind: keyof typeof sourceLabels }) {
  const [label, className] = sourceLabels[kind];
  return <span className={`f3-source-badge ${className}`}>{label}</span>;
}

export function VersionBanner({ version, stale = false, message }: { version: number; stale?: boolean; message?: string }) {
  return (
    <div className={`f3-version ${stale ? "f3-version-stale" : ""}`} role="status">
      <strong>{stale ? "版本已过期" : `当前版本 v${version}`}</strong>
      <span>{message ?? (stale ? "上游笔记已变化，请重新生成后再依赖本结果。" : "修改会创建新版本，不覆盖旧版。")}</span>
    </div>
  );
}
