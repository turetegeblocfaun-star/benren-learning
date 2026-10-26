"use client";

import { ArrowRight, FileSearch, MessageCircleQuestion, Send, ShieldCheck, Sparkles } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { Notice } from "@/components/Feedback";
import { F3Shell } from "@/components/learning/F3Shell";
import { TutorSources } from "@/components/learning/TutorSources";
import { tutorSessionSchema, tutorTurnTaskSchema, type TutorSession } from "@/features/learning/schema";
import { taskStatusSchema } from "@/features/materials/schema";
import { quizListSchema, tutorSessionListSchema } from "@/features/system/schema";
import { AppError, apiFetchContract, idempotencyKey, jsonBody, presentError } from "@/lib/api/client";

export default function TutorPage() {
  const { courseId, sessionId } = useParams<{ courseId: string; sessionId: string }>();
  const router = useRouter();
  const [message, setMessage] = useState("");
  const [latestTaskId, setLatestTaskId] = useState<string | null>(null);
  const sessionKey = ["tutor-session", sessionId];
  const tutorSessions = useQuery({ queryKey: ["tutor-sessions", courseId], queryFn: () => apiFetchContract(tutorSessionListSchema, `/api/v1/courses/${courseId}/tutor-sessions?limit=100`) });
  const quizzes = useQuery({ queryKey: ["quizzes", courseId], queryFn: () => apiFetchContract(quizListSchema, `/api/v1/courses/${courseId}/quizzes?limit=100`) });
  const session = useQuery({
    queryKey: sessionKey,
    queryFn: () => apiFetchContract(tutorSessionSchema, `/api/v1/tutor-sessions/${sessionId}`),
    refetchInterval: (query) => {
      const data = query.state.data as TutorSession | undefined;
      return ["queued", "running", "retry_wait"].includes(data?.turns.at(-1)?.status ?? "") ? 650 : false;
    },
  });
  const latest = session.data?.turns.at(-1);

  useEffect(() => {
    if (session.error instanceof AppError && session.error.status === 401) {
      router.replace(`/login?next=${encodeURIComponent(`/courses/${courseId}/tutor/${sessionId}`)}`);
    }
  }, [courseId, router, session.error, sessionId]);

  const sendText = useMutation({
    mutationFn: () => apiFetchContract(tutorTurnTaskSchema, `/api/v1/tutor-sessions/${sessionId}/turns`, {
      method: "POST", headers: { "Idempotency-Key": idempotencyKey("tutor-turn") },
      body: jsonBody({ input_mode: "text", message }),
    }),
    onSuccess: async ({ task_id }) => { setLatestTaskId(task_id); setMessage(""); await session.refetch(); },
  });

  const cancelTask = useMutation({
    mutationFn: () => {
      if (!latestTaskId) throw new Error("没有可取消的后台任务");
      return apiFetchContract(taskStatusSchema, `/api/v1/tasks/${latestTaskId}`, { method: "DELETE" });
    },
    onSuccess: async () => { setLatestTaskId(null); await session.refetch(); },
  });

  function switchSession(target: string) {
    router.push(`/courses/${courseId}/tutor/${target}`);
  }

  const busy = sendText.isPending || ["queued", "running", "retry_wait"].includes(latest?.status ?? "");
  const unavailable = session.error instanceof AppError && [403, 404].includes(session.error.status ?? 0);

  if (unavailable) {
    return (
      <F3Shell eyebrow="Tutor · 一轮一问" title="请从课程记录重新进入 Tutor" description="这个链接可能已经失效。系统不会展示会话归属或内部问题编号。" backHref="/courses">
        <section className="card">
          <h2>没有可在这里继续的 Tutor 会话</h2>
          <p className="muted">返回课程记录，打开你自己的课程，再从学习工作台进入现有 Tutor 或创建新的 Tutor。</p>
          <Link className="button button-primary" href="/courses">返回课程记录 <ArrowRight size={16} /></Link>
        </section>
      </F3Shell>
    );
  }

  return (
    <F3Shell eyebrow="Tutor · 一轮一问" title="先找到你卡住的那一步" description="Tutor 只基于当前上下文给一个最小提示和一个问题；不会显示目标答案、内部 Prompt 或推理日志。" backHref={`/courses/${courseId}/workspace`}>
      <div className="f3-tutor-mode" role="group" aria-label="Tutor 上下文模式">
        {tutorSessions.data?.map((item) => <button key={item.id} aria-pressed={sessionId === item.id} onClick={() => switchSession(item.id)}>{item.context_mode === "tutor_rag" ? <FileSearch size={17} /> : <Sparkles size={17} />}<span><strong>{item.context_mode === "tutor_rag" ? "长材料检索" : "短材料完整上下文"}</strong><small>{item.context_mode} · {item.status}</small></span></button>)}
      </div>

      {session.error ? <Notice tone="error" {...presentError(session.error)} /> : null}
      <div className="f3-tutor-layout">
        <section className="f3-chat-card" aria-busy={latest?.status === "running"}>
          <div className="f3-chat-head"><div><span className={`status-chip tone-${session.data?.context_mode === "tutor_rag" ? "running" : "success"}`}>{session.data?.context_mode ?? "读取中"}</span><h2>{session.data?.learning_goal ?? "正在读取学习目标"}</h2></div><span>{session.data?.turn_count ?? 0}/{session.data?.max_turns ?? 8} 轮</span></div>
          <div className="f3-chat-log" aria-live="polite">
            {!session.data?.turns.length ? <div className="f3-tutor-opening"><MessageCircleQuestion size={28} /><h3>{session.data?.target_problem ?? "先说说你卡住的那一步"}</h3><p>请用文字写下你的理解；Tutor 每轮只给一个最小提示和一个问题。</p></div> : session.data.turns.map((turn) => (
              <div className="f3-turn" key={turn.id}>
                <div className="f3-user-message"><small>你的回答</small><p>{turn.user_message}</p></div>
                {["queued", "running", "retry_wait"].includes(turn.status) ? (
                  <div className="f3-tutor-reply f3-tutor-running"><FileSearch className="spin-soft" size={19} /><div><strong>{session.data.context_mode === "tutor_rag" ? "正在定位所选材料中的相关原文" : "正在检查当前材料"}</strong><p>离开页面只会停止等待；任务仍按服务端状态执行。</p>{latestTaskId ? <button className="button button-ghost button-small" disabled={cancelTask.isPending} onClick={() => cancelTask.mutate()}>取消后台任务</button> : null}</div></div>
                ) : (
                  <div className="f3-tutor-reply"><MessageCircleQuestion size={19} /><div>
                    <small>{turn.status === "insufficient_context" ? "材料不足" : "Tutor 的一个问题"}</small>
                    <p>{turn.message}</p>
                    {turn.warnings.filter((warning) => !(turn.status === "insufficient_context" && warning === "检索无命中；没有使用模型记忆补答案。")).map((warning) => <span className="f3-warning" key={warning}><ShieldCheck size={13} />{warning}</span>)}
                    <TutorSources sourceIds={turn.source_ref_ids} kind={turn.source_reference_kind} />
                  </div></div>
                )}
              </div>
            ))}
          </div>
          {latest?.status === "insufficient_context" ? <div className="f3-recovery"><strong>检索无命中；没有使用模型记忆补答案。</strong><div className="cluster"><button className="button button-secondary button-small" onClick={() => setMessage("请根据当前材料，换一个能找到依据的问题引导我。")}>换成材料内问题</button><Link className="button button-ghost button-small" href={`/courses/${courseId}/materials`}>返回增选材料</Link></div></div> : null}
          <div className="f3-composer"><label htmlFor="tutor-message">本轮回答</label><textarea id="tutor-message" value={message} onChange={(event) => setMessage(event.target.value)} placeholder="写下你的理解；一次只发送一轮…" /><div><span className="small muted">Tutor 会阻断直接索要答案，改为最小提示。</span><button className="button button-primary" disabled={!message.trim() || busy} onClick={() => sendText.mutate()}><Send size={16} />{sendText.isPending ? "发送中…" : "发送本轮回答"}</button></div></div>
          {sendText.error || cancelTask.error ? <div style={{ padding: "0 18px 18px" }}><Notice tone="error" {...presentError(sendText.error ?? cancelTask.error)} /></div> : null}
        </section>
      </div>
      {quizzes.data?.[0] ? <div className="f3-footer-action"><Link className="button button-secondary" href={`/courses/${courseId}/quizzes/${quizzes.data[0].id}`}>转到客观检验 <ArrowRight size={16} /></Link></div> : null}
    </F3Shell>
  );
}
