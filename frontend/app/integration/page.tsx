"use client";

import { Activity, ArrowRight, CheckCircle2, Database, ServerCog, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { AppShell } from "@/components/AppShell";
import { LoadingCard, Notice } from "@/components/Feedback";
import { userSchema } from "@/features/materials/schema";
import { capabilitiesSchema, courseListSchema, healthSchema } from "@/features/system/schema";
import { apiFetchContract, presentError } from "@/lib/api/client";

export default function IntegrationPage() {
  const health = useQuery({ queryKey: ["integration-health"], queryFn: () => apiFetchContract(healthSchema, "/api/v1/health"), refetchInterval: 5_000 });
  const capabilities = useQuery({ queryKey: ["system-capabilities"], queryFn: () => apiFetchContract(capabilitiesSchema, "/api/v1/capabilities") });
  const user = useQuery({ queryKey: ["current-user-access"], queryFn: () => apiFetchContract(userSchema, "/api/v1/me"), retry: false });
  const courses = useQuery({ queryKey: ["courses"], queryFn: () => apiFetchContract(courseListSchema, "/api/v1/courses?limit=100"), enabled: Boolean(user.data) });
  const firstCourse = courses.data?.[0];
  const error = health.error ?? capabilities.error ?? user.error ?? courses.error;

  return (
    <AppShell>
      <main className="page-wrap acceptance-page">
        <section className="acceptance-hero">
          <div><p className="eyebrow">真实前后端联调</p><h1>每一层都来自正在运行的服务</h1><p className="lede">本页不使用合同 Mock。状态由 FastAPI、数据库、Worker、当前会话和真实 Provider 配置即时返回。</p></div>
          <div className="acceptance-progress"><strong>{health.data?.worker === "ok" ? "链路正常" : "等待 Worker"}</strong><span>每 5 秒刷新</span></div>
        </section>
        {error ? <Notice tone="error" {...presentError(error)} /> : null}
        {!health.data || !capabilities.data ? <LoadingCard label="正在读取真实服务状态…" /> : (
          <>
            <section className="f5-governance-grid" aria-label="联调服务状态">
              <article><Activity size={20} /><span>FastAPI</span><strong>{health.data.api === "ok" ? "正常" : "异常"}</strong></article>
              <article><Database size={20} /><span>数据库</span><strong>{health.data.database === "ok" ? "正常" : "异常"}</strong></article>
              <article><ServerCog size={20} /><span>后台 Worker</span><strong>{health.data.worker === "ok" ? "正常" : "未运行"}</strong></article>
              <article><ShieldCheck size={20} /><span>CSRF 来源保护</span><strong>{capabilities.data.security.csrf_origin_protection ? "开启" : "关闭"}</strong></article>
            </section>
            <section className="card" style={{ marginTop: 18 }}>
              <div className="card-head"><div><p className="eyebrow">真实供应商状态</p><h2>密钥只在后端，浏览器只看到是否可用</h2></div></div>
              <ul className="quality-gates">{Object.entries(capabilities.data.providers).map(([key, value]) => <li key={key}><CheckCircle2 size={17} /><span>{key} · {value.provider} · {value.configured ? "已配置" : "未配置"}</span></li>)}</ul>
            </section>
            <section className="card" style={{ marginTop: 18 }}>
              <div className="card-head"><div><p className="eyebrow">可继续验证</p><h2>{firstCourse ? firstCourse.title ?? "未命名课程" : "还没有课程记录"}</h2></div></div>
              <div className="cluster">{firstCourse ? <><Link className="button button-primary" href={`/courses/${firstCourse.id}/materials`}>上传与材料状态 <ArrowRight size={16} /></Link><Link className="button button-secondary" href={`/courses/${firstCourse.id}/workspace`}>学习与计划闭环</Link></> : <Link className="button button-primary" href="/courses/new">创建并上传第一份材料</Link>}<Link className="button button-secondary" href="/controlled">受控能力与失败状态</Link></div>
            </section>
          </>
        )}
      </main>
    </AppShell>
  );
}
