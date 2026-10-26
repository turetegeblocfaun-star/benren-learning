"use client";

import { Activity, AlertTriangle, Gauge, LockKeyhole, ShieldCheck } from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { LoadingCard, Notice } from "@/components/Feedback";
import { F5Shell } from "@/components/controlled/F5Shell";
import { governanceMetricsSchema } from "@/features/controlled/schema";
import { apiFetchContract, presentError } from "@/lib/api/client";

export default function GovernancePage() {
  const metrics = useQuery({ queryKey: ["f5-governance"], queryFn: () => apiFetchContract(governanceMetricsSchema, "/api/v1/governance/metrics") });
  return <F5Shell eyebrow="F5 · 内部治理" title="看系统是否守规矩，不看用户原文" description="治理页只聚合工作流、任务、守卫、反馈、适配器和性能状态。它不是内容监控后台，也不应成为绕过用户隐私的入口。" gate="governance" backHref="/controlled">
    {metrics.isPending ? <LoadingCard label="正在读取脱敏治理指标…" /> : metrics.error ? <Notice tone="error" {...presentError(metrics.error)} /> : metrics.data ? <>
      <div className="f5-governance-grid"><article><Activity size={20} /><span>已完成工作流</span><strong>{metrics.data.workflow_runs.completed ?? 0}</strong></article><article><AlertTriangle size={20} /><span>失败任务</span><strong>{metrics.data.jobs.failed ?? 0}</strong></article><article><ShieldCheck size={20} /><span>守卫命中</span><strong>{Object.values(metrics.data.guardrails).reduce((a,b) => a+b,0)}</strong></article><article><Gauge size={20} /><span>P95 延迟</span><strong>{String(metrics.data.performance.p95_ms ?? "—")} ms</strong></article></div>
      <div className="f5-two-grid"><section className="f5-panel"><div className="f5-panel-head"><div><p className="eyebrow">外部适配器</p><h2>配置状态不是成功状态</h2></div></div><dl className="f5-adapters">{Object.entries(metrics.data.external_adapters).map(([key,value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl></section><section className="f5-panel"><div className="f5-panel-head"><div><p className="eyebrow">守卫与反馈</p><h2>只展示计数</h2></div></div><dl className="f5-adapters">{[...Object.entries(metrics.data.guardrails),...Object.entries(metrics.data.feedback)].map(([key,value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl></section></div>
      <section className="f5-redaction"><LockKeyhole size={20} /><div><strong>治理数据已限制为聚合指标</strong><p>无 API Key、OAuth Token、材料正文、用户回答、Tutor 对话、Prompt 或推理过程。详细运行仍需按已知且有权限的 run ID 查询。</p></div></section>
    </> : null}
  </F5Shell>;
}
