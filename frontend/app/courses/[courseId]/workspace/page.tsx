"use client";

import { ArrowRight, BookOpenText, BrainCircuit, Clock3, GitBranch, MessageCircleQuestion, NotebookPen, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";

import { LoadingCard, Notice } from "@/components/Feedback";
import { F3Shell } from "@/components/learning/F3Shell";
import { F4Workspace } from "@/components/planning/F4Workspace";
import { learningAssetTaskSchema, workspaceSchema } from "@/features/learning/schema";
import { contextSnapshotSchema, materialListSchema } from "@/features/materials/schema";
import { learningAssetListSchema, quizListSchema, tutorSessionListSchema } from "@/features/system/schema";
import { apiFetchContract, idempotencyKey, jsonBody, presentError } from "@/lib/api/client";

function F3LearningWorkspace() {
  const { courseId } = useParams<{ courseId: string }>();
  const router = useRouter();
  const workspace = useQuery({ queryKey: ["f3-workspace", courseId], queryFn: () => apiFetchContract(workspaceSchema, `/api/v1/courses/${courseId}/workspace`) });
  const materials = useQuery({ queryKey: ["materials", courseId, "usable"], queryFn: () => apiFetchContract(materialListSchema, `/api/v1/courses/${courseId}/materials?status=usable`) });
  const assets = useQuery({ queryKey: ["learning-assets", courseId], queryFn: () => apiFetchContract(learningAssetListSchema, `/api/v1/courses/${courseId}/learning-assets?limit=100`) });
  const quizzes = useQuery({ queryKey: ["quizzes", courseId], queryFn: () => apiFetchContract(quizListSchema, `/api/v1/courses/${courseId}/quizzes?limit=100`) });
  const tutorSessions = useQuery({ queryKey: ["tutor-sessions", courseId], queryFn: () => apiFetchContract(tutorSessionListSchema, `/api/v1/courses/${courseId}/tutor-sessions?limit=100`) });
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

  if (workspace.data?.action.type === "generate_review_plan" || workspace.data?.action.type === "note_review") {
    return <F4Workspace courseId={courseId} />;
  }

  const note = assets.data?.find((item) => item.asset_type === "note" && item.status !== "failed");
  const graph = assets.data?.find((item) => item.asset_type === "graph" && item.status !== "failed");
  const quiz = quizzes.data?.find((item) => item.status !== "failed");
  const tutor = tutorSessions.data?.find((item) => item.status === "active") ?? tutorSessions.data?.[0];
  const links = [
    note ? { icon: NotebookPen, title: "结构化笔记", text: "五类来源分层、来源回跳、人工修订与版本保留。", href: `notes/${note.id}`, meta: `v${note.version} · ${note.status}` } : null,
    graph ? { icon: GitBranch, title: "知识图谱", text: "概念、关系、掌握态与可访问的概念列表等价视图。", href: `graph/${graph.id}`, meta: `v${graph.version} · ${graph.status}` } : null,
    quiz ? { icon: BrainCircuit, title: "客观测验", text: "提交前不泄答；提交后用代码确定性判分并进入错题本。", href: `quizzes/${quiz.id}`, meta: `${quiz.published_count} 道可作答题` } : null,
    tutor ? { icon: MessageCircleQuestion, title: "引导式 Tutor", text: "使用文字一轮一问，支持 RAG 无命中后的安全恢复。", href: `tutor/${tutor.id}`, meta: tutor.context_mode } : null,
  ].filter((item): item is NonNullable<typeof item> => item !== null);

  return (
    <F3Shell eyebrow="F3 · 学习闭环" title="把材料变成可验证的理解" description="这一阶段只使用你已经确认的材料。每个结论能回到来源，每次修改保留版本，每次练习都能解释下一步。">
      {workspace.isPending ? <LoadingCard label="正在计算本次唯一下一步…" /> : workspace.error ? <Notice tone="error" {...presentError(workspace.error)} /> : workspace.data ? (
        <section className="f3-next-card" aria-labelledby="next-action-title">
          <div>
            <p className="eyebrow">唯一下一步 · Workflow 决定</p>
            <h2 id="next-action-title">先整理一份可追溯的结构化笔记</h2>
            <p>{workspace.data.action.reason}</p>
            <div className="cluster f3-next-meta"><span><Clock3 size={15} />约 {workspace.data.action.duration_min} 分钟</span><span><ShieldCheck size={15} />不使用当前材料外的模型记忆</span></div>
          </div>
          <button className="button f3-primary-action" onClick={() => generateNote.mutate()} disabled={generateNote.isPending || materials.isPending || workspace.data.action.type !== "generate_note"}>
            {generateNote.isPending ? "正在受理笔记任务…" : <>整理结构笔记 <ArrowRight size={18} /></>}
          </button>
        </section>
      ) : null}
      {generateNote.error ? <div style={{ marginTop: 16 }}><Notice tone="error" {...presentError(generateNote.error)} /></div> : null}

      <section className="f3-section">
        <div className="f3-section-heading"><div><p className="eyebrow">学习工具</p><h2>一个闭环，四个检查点</h2></div><p>列表来自后端当前课程，刷新后可恢复，不依赖写死 ID。</p></div>
        {links.length ? <div className="f3-tool-grid">
          {links.map(({ icon: Icon, ...item }) => (
            <Link className="f3-tool-card" href={`/courses/${courseId}/${item.href}`} key={item.title}>
              <span className="f3-tool-icon"><Icon size={21} /></span><small>{item.meta}</small><h3>{item.title}</h3><p>{item.text}</p><span className="f3-card-link">打开并验证 <ArrowRight size={15} /></span>
            </Link>
          ))}
        </div> : <section className="f3-empty-state"><BookOpenText size={25} /><h3>还没有已生成的学习工具</h3><p>先完成上方唯一下一步，生成结果会自动出现在这里。</p></section>}
      </section>

      <section className="f3-contract-strip" aria-label="F3 合同约束">
        <div><BookOpenText size={18} /><span><strong>来源先行</strong>没有 SourceRef 的内容会标出来源层级</span></div>
        <div><ShieldCheck size={18} /><span><strong>答案隔离</strong>题目接口与提交结果严格分开</span></div>
        <div><MessageCircleQuestion size={18} /><span><strong>一轮一问</strong>Tutor 不展示答案、Prompt 或推理日志</span></div>
      </section>
    </F3Shell>
  );
}

export default function LearningWorkspacePage() {
  return <F3LearningWorkspace />;
}
