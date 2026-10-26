"use client";

import { ArrowRight, KeyRound, Layers3 } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useState } from "react";

import { Brand } from "@/components/AppShell";
import { Notice } from "@/components/Feedback";
import { courseSchema, sessionSchema } from "@/features/materials/schema";
import { apiFetchContract, jsonBody, presentError } from "@/lib/api/client";
import { runtimeStatus } from "@/lib/runtime";

const DEFAULT_WORKSPACE_KEY = "default-material-workspace-v1";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ message: string; detail?: string } | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setError(null);
    try {
      await apiFetchContract(sessionSchema, "/api/v1/auth/invite-session", {
        method: "POST",
        body: jsonBody({ invite_code: code.trim() }),
      });
      const next = params.get("next");
      if (next?.startsWith("/") && next !== "/courses/new") {
        router.replace(next);
        return;
      }
      const course = await apiFetchContract(courseSchema, "/api/v1/courses", {
        method: "POST",
        headers: { "Idempotency-Key": DEFAULT_WORKSPACE_KEY },
        body: jsonBody({ temporary_title: null }),
      });
      localStorage.setItem(
        "bl_recent_course",
        JSON.stringify({
          id: course.id,
          title: course.title ?? "未命名课程",
          savedAt: new Date().toISOString(),
        }),
      );
      router.replace(`/courses/${course.id}/materials`);
    } catch (caught) {
      setError(presentError(caught));
    } finally { setBusy(false); }
  }

  return (
    <form className="card login-card stack" onSubmit={submit}>
      <div><p className="eyebrow">安全入口</p><h2>输入你的邀请码</h2><p className="muted">邀请码只用来确认你的身份。模型密钥永远不会进入这个页面。</p></div>
      {error ? <Notice tone="error" {...error} /> : null}
      <div className="field">
        <label htmlFor="invite-code">邀请码</label>
        <div style={{ position: "relative" }}>
          <KeyRound size={18} aria-hidden="true" style={{ position: "absolute", left: 13, top: 14, color: "var(--muted)" }} />
          <input id="invite-code" className="input" style={{ paddingLeft: 41 }} value={code} onChange={(event) => setCode(event.target.value)} autoComplete="one-time-code" minLength={8} maxLength={256} required placeholder="输入至少 8 位邀请码" />
        </div>
      </div>
      <button className="button button-primary" type="submit" disabled={busy || code.trim().length < 8}>{busy ? "正在打开上传页…" : <>进入材料工作台 <ArrowRight size={17} /></>}</button>
      <p className="small muted" style={{ marginBottom: 0 }}>如果邀请码不正确，请联系给你发送网址的人，不要反复尝试。</p>
    </form>
  );
}

export default function LoginPage() {
  return (
    <main className="login-shell">
      <section className="login-story">
        <Brand />
        <div><p className="eyebrow" style={{ color: "#d1af74" }}>先把材料讲清楚</p><h1>学习不必快，<br />但每一步要有出处。</h1><p>上传已有音频、图片、Word、PDF 和 Markdown 文档。系统先整理、让你确认，再把它们编排成完整且可追溯的学习上下文。</p></div>
        <div className="cluster small"><Layers3 size={17} /><span>{runtimeStatus.stage} · {runtimeStatus.badge}</span></div>
      </section>
      <section className="login-panel"><Suspense fallback={<div className="card login-card">正在准备登录…</div>}><LoginForm /></Suspense></section>
    </main>
  );
}
