"use client";

import { ArrowRight, CheckCircle2, History, Link2, RotateCcw } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { EmptyState, LoadingCard, Notice } from "@/components/Feedback";
import { F3Shell } from "@/components/learning/F3Shell";
import { quizAttemptSchema, quizSchema, wrongbookSchema } from "@/features/learning/schema";
import { quizListSchema } from "@/features/system/schema";
import { apiFetchContract, idempotencyKey, jsonBody, presentError } from "@/lib/api/client";

export default function WrongbookPage() {
  const { courseId } = useParams<{ courseId: string }>();
  const queryClient = useQueryClient();
  const [answer, setAnswer] = useState("");
  const wrongbook = useQuery({ queryKey: ["wrongbook", courseId], queryFn: () => apiFetchContract(wrongbookSchema, `/api/v1/courses/${courseId}/wrongbook`) });
  const entry = wrongbook.data?.[0];
  const quizzes = useQuery({ queryKey: ["quizzes", courseId], queryFn: () => apiFetchContract(quizListSchema, `/api/v1/courses/${courseId}/quizzes?limit=100`) });
  const quizId = quizzes.data?.find((item) => item.status !== "failed")?.id;
  const quiz = useQuery({
    queryKey: ["quiz", quizId],
    queryFn: () => apiFetchContract(quizSchema, `/api/v1/quizzes/${quizId}`),
    enabled: entry?.status === "needs_review" && Boolean(quizId),
  });
  const question = quiz.data?.questions.find((item) => item.id === entry?.question_id);
  const retry = useMutation({
    mutationFn: () => {
      if (!entry || !question) throw new Error("错题内容尚未恢复");
      return apiFetchContract(quizAttemptSchema, `/api/v1/quiz-questions/${entry.question_id}/attempts`, { method: "POST", headers: { "Idempotency-Key": idempotencyKey("wrong-retry") }, body: jsonBody({ selected_answer: answer }) });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["wrongbook", courseId] });
      await queryClient.invalidateQueries({ queryKey: ["quiz", quizId] });
      setAnswer("");
    },
  });

  if (wrongbook.isPending) return <F3Shell eyebrow="错题本" title="正在读取纠正历史" description="错题由后端状态去重。"><LoadingCard label="正在读取错题本…" /></F3Shell>;
  if (wrongbook.error) return <F3Shell eyebrow="错题本" title="错题本没有成功打开" description="读取失败不会清空作答历史。"><Notice tone="error" {...presentError(wrongbook.error)} /></F3Shell>;

  return (
    <F3Shell eyebrow="错题本 · 5 分钟重练" title={entry ? "把一次错误变成一条纠正记录" : "还没有需要重练的题"} description="重复做错不会在前端复制条目；答对后同一条记录转为已纠正，并保留全过程。" backHref={quizId ? `/courses/${courseId}/quizzes/${quizId}` : `/courses/${courseId}/workspace`}>
      {!entry ? <section className="card"><EmptyState title="先完成一次概念检验" text="测验答错后，这里会出现同一条后端错题记录和纠正历史。" />{quizId ? <div className="f3-footer-action"><Link className="button button-primary" href={`/courses/${courseId}/quizzes/${quizId}`}>去做测验 <ArrowRight size={16} /></Link></div> : null}</section> : (
        <section className="f3-wrong-card">
          <div className="f3-wrong-head"><div><p className="eyebrow">{entry.status === "resolved" ? "已纠正" : "需要复习"}</p><h2>{entry.stem}</h2></div><span className={`status-chip tone-${entry.status === "resolved" ? "success" : "warning"}`}>{entry.status === "resolved" ? "已纠正" : `错 ${entry.wrong_count} 次`}</span></div>
          {entry.status === "needs_review" ? <div className="f3-retry-area"><p>选择完整选项后提交；后端判分完成前仍不会显示正确答案。</p>{quiz.isPending ? <LoadingCard label="正在恢复原题选项…" /> : quiz.error || !question ? <Notice tone="error" message="原题选项暂时无法恢复，已阻止只凭字母作答。" detail="请返回原测验重试，系统不会提交不完整答案。" /> : <><div className="f3-retry-options">{question.options.map((option) => <button className={answer === option.id ? "selected" : ""} aria-pressed={answer === option.id} onClick={() => setAnswer(option.id)} key={option.id}><span>{option.id}</span><strong>{option.text}</strong></button>)}</div><button className="button button-primary" disabled={!answer || retry.isPending} onClick={() => retry.mutate()}><RotateCcw size={16} />{retry.isPending ? "正在判分…" : "提交重练答案"}</button></>}</div> : <div className="notice notice-success"><CheckCircle2 size={18} /><p>这条错题已经纠正。题目随后被撤回时，历史仍保留，但不再计入掌握或错题影响。</p></div>}
          {retry.data ? <div style={{ marginTop: 14 }}><Notice tone={retry.data.is_correct ? "success" : "info"} message={retry.data.is_correct ? "本次重练正确，错题状态已由后端改为已纠正。" : "这次仍未答对；同一条错题记录已更新，没有新增重复条目。"} detail={retry.data.explanation} /><div className="cluster" style={{ marginTop: 10 }}>{retry.data.source_ref_ids.map((id) => <Link className="f3-source-link" href={`/sources/${id}`} key={id}><Link2 size={14} />查看课堂依据</Link>)}</div></div> : null}
          {retry.error ? <div style={{ marginTop: 14 }}><Notice tone="error" {...presentError(retry.error)} /></div> : null}
          <details className="f3-history"><summary><History size={16} />纠正历史（{entry.history.length}）</summary><ol>{entry.history.map((item, index) => <li key={index}>第 {index + 1} 次 · 选择 {String(item.selected_answer)} · {item.is_correct ? "正确" : "错误"}</li>)}</ol></details>
        </section>
      )}
      {entry?.status === "resolved" && quizId ? <div className="f3-footer-action"><Link className="button button-secondary" href={`/courses/${courseId}/quizzes/${quizId}`}>返回查看题目撤回状态 <ArrowRight size={16} /></Link></div> : null}
    </F3Shell>
  );
}
