"use client";

import { ArrowRight, BookX, CheckCircle2, Link2, LockKeyhole, RotateCcw, XCircle } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { LoadingCard, Notice } from "@/components/Feedback";
import { F3Shell } from "@/components/learning/F3Shell";
import { quizAttemptSchema, quizSchema, quizTaskSchema, type Quiz, type QuizAttempt } from "@/features/learning/schema";
import { contextSnapshotSchema, materialListSchema } from "@/features/materials/schema";
import { apiFetchContract, idempotencyKey, jsonBody, presentError } from "@/lib/api/client";

export default function QuizPage() {
  const { courseId, quizId } = useParams<{ courseId: string; quizId: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState("");
  const [result, setResult] = useState<QuizAttempt | null>(null);
  const quiz = useQuery({
    queryKey: ["quiz", quizId],
    queryFn: () => apiFetchContract(quizSchema, `/api/v1/quizzes/${quizId}`),
    refetchInterval: (query) => {
      const data = query.state.data as Quiz | undefined;
      return data && !["ready", "partial", "failed", "cancelled"].includes(data.status) ? 750 : false;
    },
  });
  const active = quiz.data?.questions.find((question) => question.status === "active");
  const withdrawn = quiz.data?.questions.filter((question) => question.status === "withdrawn") ?? [];
  const materials = useQuery({ queryKey: ["materials", courseId, "usable"], queryFn: () => apiFetchContract(materialListSchema, `/api/v1/courses/${courseId}/materials?status=usable`) });
  const attempt = useMutation({
    mutationFn: () => {
      if (!active) throw new Error("没有可作答的题目");
      return apiFetchContract(quizAttemptSchema, `/api/v1/quiz-questions/${active.id}/attempts`, { method: "POST", headers: { "Idempotency-Key": idempotencyKey("attempt") }, body: jsonBody({ selected_answer: selected }) });
    },
    onSuccess: (data) => { setResult(data); void queryClient.invalidateQueries({ queryKey: ["wrongbook", courseId] }); },
  });
  const generateNew = useMutation({
    mutationFn: async () => {
      const selected = materials.data?.items.filter((item) => item.active_parse_version_id) ?? [];
      if (!selected.length) throw new Error("没有可用于生成新题的材料版本");
      const snapshot = await apiFetchContract(contextSnapshotSchema, `/api/v1/courses/${courseId}/context-snapshots`, {
        method: "POST", headers: { "Idempotency-Key": idempotencyKey("quiz-context-regenerate") },
        body: jsonBody({ task_type: "quiz", selected_materials: selected.map((item, selected_order) => ({ id: item.id, parse_version: item.active_parse_version_id, selected_order })) }),
      });
      return apiFetchContract(quizTaskSchema, `/api/v1/courses/${courseId}/quizzes`, {
        method: "POST", headers: { "Idempotency-Key": idempotencyKey("quiz-regenerate") },
        body: jsonBody({ context_snapshot_id: snapshot.id, difficulty: quiz.data?.difficulty ?? "medium", count: 3, question_types: ["single_choice", "true_false"] }),
      });
    },
    onSuccess: ({ quiz: nextQuiz }) => router.push(`/courses/${courseId}/quizzes/${nextQuiz.id}`),
  });

  if (quiz.isPending || (quiz.data && !["ready", "partial", "failed", "cancelled"].includes(quiz.data.status))) return <F3Shell eyebrow="客观测验" title="正在发布可作答题目" description="正确答案不会随取题接口下发。"><LoadingCard label="DeepSeek 正在生成并复核题目，页面会自动更新…" /></F3Shell>;
  if (quiz.error) return <F3Shell eyebrow="客观测验" title="测验没有成功打开" description="可以安全重试，作答幂等键不会重复计分。"><Notice tone="error" {...presentError(quiz.error)} /></F3Shell>;
  if (quiz.data?.status === "failed") return <F3Shell eyebrow="客观测验" title="测验生成失败" description="上下文仍然保留，可以重新生成。"><Notice tone="error" message={quiz.data.error_message ?? "测验生成没有成功。"} /></F3Shell>;

  return (
    <F3Shell eyebrow="客观测验 · 确定性判分" title="先作答，再看依据" description="提交前只显示题干和选项。正确答案、解析与来源只有在后端完成规则判分后才出现。" backHref={`/courses/${courseId}/workspace`} actions={<Link className="button button-secondary" href={`/courses/${courseId}/wrongbook`}><BookX size={16} />打开错题本</Link>}>
      <div className="f3-quiz-meta"><span>难度 · {quiz.data?.difficulty ?? "—"}</span><span>已发布 · {quiz.data?.published_count ?? 0}</span><span><LockKeyhole size={14} />提交前答案隔离</span></div>
      {active ? (
        <section className="f3-quiz-card">
          <div className="f3-question-number">01</div>
          <div className="f3-question-main">
            <p className="eyebrow">单项选择 · 概念检验</p>
            <h2>{active.stem}</h2>
            <fieldset className="f3-options" disabled={Boolean(result) || attempt.isPending}>
              <legend className="sr-only">请选择一个答案</legend>
              {active.options.map((option) => <label className={selected === option.id ? "f3-option f3-option-selected" : "f3-option"} key={option.id}><input type="radio" name="answer" value={option.id} checked={selected === option.id} onChange={() => setSelected(option.id)} /><span>{option.id}</span><strong>{option.text}</strong></label>)}
            </fieldset>
            {!result ? <div className="f3-submit-row"><span className="small muted">未选择答案时不能提交；重复点击不会生成重复作答。</span><button className="button button-primary" disabled={!selected || attempt.isPending} onClick={() => attempt.mutate()}>{attempt.isPending ? "正在判分…" : "提交当前答案"}</button></div> : (
              <div className={`f3-result ${result.is_correct ? "f3-result-correct" : "f3-result-wrong"}`} role="status">
                <div>{result.is_correct ? <CheckCircle2 size={25} /> : <XCircle size={25} />}<div><p className="eyebrow">{result.is_correct ? "回答正确" : "这次还没答对"}</p><h3>正确答案：{result.correct_answer}</h3></div></div>
                <p>{result.explanation}</p>
                <div className="cluster">{result.source_ref_ids.map((id) => <Link className="f3-source-link" href={`/sources/${id}`} key={id}><Link2 size={14} />查看课堂依据</Link>)}{!result.is_correct ? <Link className="button button-secondary button-small" href={`/courses/${courseId}/wrongbook`}>进入错题重练 <ArrowRight size={14} /></Link> : null}</div>
              </div>
            )}
            {attempt.error ? <Notice tone="error" {...presentError(attempt.error)} /> : null}
          </div>
        </section>
      ) : <section className="card"><Notice tone="info" message="当前没有可作答题目。" detail="题目已撤回，不计入掌握态或错题影响。你可以基于当前已确认材料生成一组新题。" /><div className="f3-footer-action"><button className="button button-primary" onClick={() => generateNew.mutate()} disabled={generateNew.isPending || materials.isPending}>{generateNew.isPending ? "正在生成新题…" : "生成一组新题"}</button></div>{generateNew.error ? <Notice tone="error" {...presentError(generateNew.error)} /> : null}</section>}

      {withdrawn.length ? <section className="f3-withdrawn"><BookX size={21} /><div><h2>题目已撤回</h2><p>{withdrawn.length} 道题因版本或质量原因停止作答。它们不会计入掌握度、错题数或复习推荐。</p></div></section> : null}
      <div className="f3-footer-action"><button className="button button-secondary" onClick={() => { setSelected(""); setResult(null); void quiz.refetch(); }}><RotateCcw size={16} />刷新后端题目状态</button></div>
    </F3Shell>
  );
}
