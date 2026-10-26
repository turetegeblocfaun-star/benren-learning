"use client";

import { Check, Database, FlaskConical, GraduationCap, LockKeyhole, Play, ShieldCheck, X } from "lucide-react";
import { useParams } from "next/navigation";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { LoadingCard, Notice } from "@/components/Feedback";
import { F5Shell, F5Status } from "@/components/controlled/F5Shell";
import { sftConsentSchema, sftDatasetSchema, sftEvaluationSchema, sftProjectSchema } from "@/features/controlled/schema";
import { learningAssetSchema } from "@/features/learning/schema";
import { capabilitiesSchema, courseListSchema, learningAssetListSchema } from "@/features/system/schema";
import { apiFetchContract, jsonBody, presentError } from "@/lib/api/client";
import { isContractMock } from "@/lib/runtime";

const gates = [
  ["baseline_residual_exists", "基线仍有明确残差"], ["authorized_dataset_ready", "数据逐条获得用途授权"],
  ["independent_evaluation_ready", "评测集与训练集独立"], ["quality_target_passed", "候选结果达到质量目标"], ["safety_passed", "安全评测通过"],
] as const;

export default function SftGatePage() {
  const { projectId } = useParams<{ projectId: string }>(); const client = useQueryClient();
  const [consentId, setConsentId] = useState<string | null>(null); const [datasetId, setDatasetId] = useState<string | null>(null); const [message, setMessage] = useState("");
  const project = useQuery({ queryKey: ["f5-sft", projectId], queryFn: () => apiFetchContract(sftProjectSchema, `/api/v1/sft/projects/${projectId}/gate`) });
  const capabilities = useQuery({ queryKey: ["system-capabilities"], queryFn: () => apiFetchContract(capabilitiesSchema, "/api/v1/capabilities") });
  const courses = useQuery({ queryKey: ["courses"], queryFn: () => apiFetchContract(courseListSchema, "/api/v1/courses?limit=100") });
  const sourceCourseId = courses.data?.[0]?.id;
  const assets = useQuery({ queryKey: ["learning-assets", sourceCourseId], queryFn: () => apiFetchContract(learningAssetListSchema, `/api/v1/courses/${sourceCourseId}/learning-assets?limit=100`), enabled: Boolean(sourceCourseId) });
  const noteAssetId = assets.data?.find((item) => item.asset_type === "note" && item.current_version_id)?.id;
  const noteAsset = useQuery({ queryKey: ["learning-asset", noteAssetId], queryFn: () => apiFetchContract(learningAssetSchema, `/api/v1/learning-assets/${noteAssetId}`), enabled: Boolean(noteAssetId) });
  const sourceRefId = noteAsset.data?.current_version?.source_ref_ids[0] ?? (isContractMock ? "source-f3-example" : null);
  const sftProvider = capabilities.data?.providers.sft;
  const refresh = () => client.invalidateQueries({ queryKey: ["f5-sft", projectId] });
  const consent = useMutation({ mutationFn: () => {
    if (!sourceRefId) throw new Error("请先生成一份带课堂来源的结构化笔记，再授权训练来源");
    return apiFetchContract(sftConsentSchema, `/api/v1/sft/projects/${projectId}/consents`, { method: "POST", body: jsonBody({ source_ref_id: sourceRefId, purpose_version: "sft-purpose-v1" }) });
  }, onSuccess: (value) => { setConsentId(value.consent_id); setMessage("已记录这 1 条真实来源的特定用途授权。") } });
  const dataset = useMutation({ mutationFn: () => apiFetchContract(sftDatasetSchema, `/api/v1/sft/projects/${projectId}/datasets`, { method: "POST", body: jsonBody({ consent_ids: [consentId] }) }), onSuccess: async (value) => { setDatasetId(value.dataset_snapshot_id); setMessage("授权数据已冻结为不可变快照。"); await refresh(); } });
  const evaluate = useMutation({ mutationFn: () => apiFetchContract(sftEvaluationSchema, `/api/v1/sft/projects/${projectId}/evaluations`, { method: "POST", body: jsonBody({ dataset_snapshot_id: datasetId, evaluation_set_hash: "a".repeat(64), independent_from_training: true, candidate_score: .9, safety_passed: true }) }), onSuccess: async () => { setMessage("独立质量与安全评测已记录，Gate 已重新计算。"); await refresh(); } });
  const launch = useMutation({ mutationFn: () => apiFetchContract(sftProjectSchema, `/api/v1/sft/projects/${projectId}/launch`, { method: "POST" }), onSuccess: async () => { setMessage(isContractMock ? "五重门全部通过，训练任务已提交给 Mock Provider。" : `五重门全部通过，训练任务已提交给 ${sftProvider?.provider ?? "已配置"} Provider。`); await refresh(); } });
  const error = consent.error ?? dataset.error ?? evaluate.error ?? launch.error;
  const report = project.data?.gate_report ?? {};
  return <F5Shell eyebrow="F5 · P2 SFT 治理" title="先过五重门，再允许发起训练" description="训练不是默认升级路径。只有基线问题真实存在、数据有授权、独立评测、质量、安全与基线残差全部通过才能发起。" gate="sft" backHref="/controlled">
    {project.isPending ? <LoadingCard label="正在重新计算 SFT Gate…" /> : project.error ? <Notice tone="error" {...presentError(project.error)} /> : project.data ? <>
      <section className="f5-sft-hero"><div><GraduationCap size={25} /><div><p className="eyebrow">{project.data.name}</p><h2>{project.data.use_case}</h2><span>基线 {project.data.baseline_score} → 目标 {project.data.target_score}</span></div></div><F5Status value={project.data.status} /></section>
      <div className="f5-gate-grid">{gates.map(([key,label],index) => { const passed = Boolean(report[key]); return <article className={passed ? "passed" : "blocked"} key={key}><span>{passed ? <Check size={15} /> : <X size={15} />}</span><small>GATE 0{index+1}</small><strong>{label}</strong><p>{passed ? "已满足" : "尚未满足，训练发起会被后端拒绝"}</p></article> })}</div>
      <section className="f5-sft-actions"><button className="button button-secondary" onClick={() => { setMessage(""); launch.mutate(); }} disabled={launch.isPending}><LockKeyhole size={15} />验证未过门时阻止发起</button><span /><button className="button button-secondary" onClick={() => consent.mutate()} disabled={Boolean(consentId) || !sourceRefId}><ShieldCheck size={15} />1. 授权一条来源</button><button className="button button-secondary" onClick={() => dataset.mutate()} disabled={!consentId || Boolean(datasetId)}><Database size={15} />2. 冻结数据快照</button><button className="button button-secondary" onClick={() => evaluate.mutate()} disabled={!datasetId || Boolean(report.independent_evaluation_ready)}><FlaskConical size={15} />3. 记录独立评测</button><button className="button button-primary" onClick={() => launch.mutate()} disabled={!Boolean(report.eligible_to_launch) || launch.isPending}><Play size={15} />4. 发起训练</button></section>
      {message ? <div className="f5-feedback"><Notice tone="success" message={message} /></div> : null}{error ? <div className="f5-feedback"><Notice tone="error" {...presentError(error)} /></div> : null}
      {!sourceRefId ? <Notice tone="info" message="当前没有可授权的真实来源" detail="请先在课程学习台生成一份带课堂来源的结构化笔记。" /> : null}
      <section className="f5-boundary"><ShieldCheck size={19} /><div><strong>Provider 配置不是五重门的替代品</strong><p>当前 SFT Provider：{sftProvider?.configured ? sftProvider.provider : "未配置"}。即便 Provider 已配置，任一业务/授权/评测 Gate 失败仍必须阻止发起；页面不展示训练原文或供应商密钥。</p></div></section>
    </> : null}
  </F5Shell>;
}
