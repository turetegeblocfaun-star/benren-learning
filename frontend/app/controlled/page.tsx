"use client";

import { ArrowRight, BookCheck, Building2, CalendarSync, GraduationCap, Link2, LockKeyhole, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Notice } from "@/components/Feedback";
import { F5Shell } from "@/components/controlled/F5Shell";
import { organizationListSchema, organizationSchema, sftProjectListSchema, sftProjectSchema } from "@/features/controlled/schema";
import { courseListSchema } from "@/features/system/schema";
import { apiFetchContract, jsonBody, presentError } from "@/lib/api/client";
import { isContractMock } from "@/lib/runtime";

export default function ControlledHubPage() {
  const router = useRouter();
  const client = useQueryClient();
  const courses = useQuery({ queryKey: ["courses"], queryFn: () => apiFetchContract(courseListSchema, "/api/v1/courses?limit=100") });
  const organizations = useQuery({ queryKey: ["organizations"], queryFn: () => apiFetchContract(organizationListSchema, "/api/v1/organizations?limit=100") });
  const sftProjects = useQuery({ queryKey: ["sft-projects"], queryFn: () => apiFetchContract(sftProjectListSchema, "/api/v1/sft/projects?limit=100") });
  const courseId = courses.data?.[0]?.id;
  const organizationId = organizations.data?.[0]?.id;
  const sftProjectId = sftProjects.data?.[0]?.id;
  const createOrganization = useMutation({
    mutationFn: () => apiFetchContract(organizationSchema, "/api/v1/organizations", { method: "POST", body: jsonBody({ name: "我的学习组织" }) }),
    onSuccess: async (organization) => { await client.invalidateQueries({ queryKey: ["organizations"] }); router.push(`/admin/organizations/${organization.id}`); },
  });
  const createSftProject = useMutation({
    mutationFn: () => apiFetchContract(sftProjectSchema, "/api/v1/sft/projects", { method: "POST", body: jsonBody({ name: "Tutor 引导表达改进", use_case: "验证基线仍未解决的引导表达问题", baseline_metric_name: "golden_set_pass_rate", baseline_score: 0.6, target_score: 0.85 }) }),
    onSuccess: async (project) => { await client.invalidateQueries({ queryKey: ["sft-projects"] }); router.push(`/admin/sft/${project.id}`); },
  });
  const capabilities = [
    { tier: "P1", icon: BookCheck, title: "主观自评与自适应复习", text: "用户依据 Rubric 自评，不做自动对错判定；复习间隔说明真实证据。", href: courseId ? `/controlled/courses/${courseId}/practice` : null, gate: courseId ? "课程已恢复" : "暂无课程" },
    { tier: "P1", icon: CalendarSync, title: "外部日历同步", text: "OAuth 权限、写入提案、影响预览、逐次确认、拉取与撤销。", href: "/controlled/external-calendar", gate: "Provider + HTTPS" },
    { tier: "P2", icon: Building2, title: "组织与班级聚合", text: "管理员可编排班级和课程，只看聚合指标，不展示任何学习原文。", href: organizationId ? `/admin/organizations/${organizationId}` : null, gate: organizationId ? "管理员角色" : "尚未创建组织" },
    { tier: "P2", icon: Link2, title: "显式跨课关联", text: "用户选择具体来源和目的后创建，可随时撤销，不做静默跨课复用。", href: "/controlled/cross-course", gate: "明确选择来源" },
    { tier: "P2", icon: GraduationCap, title: "SFT 五重门", text: "授权数据、独立评测、质量、安全与基线残差全部通过才能发起。", href: sftProjectId ? `/admin/sft/${sftProjectId}` : null, gate: sftProjectId ? "五重门全部通过" : "尚未创建项目" },
    { tier: "内部", icon: LockKeyhole, title: "治理指标", text: "只展示聚合状态、守卫命中和适配器健康，不展示原文与密钥。", href: "/admin/governance", gate: "内部角色" },
  ];
  return <F5Shell eyebrow="F5 · 受控能力" title="能力可以很强，入口必须克制" description="这些页面不属于普通学习者的主流程。每一项都要同时满足功能开关、角色权限、Provider 配置和用户确认；缺一项就明确阻止。">
    <section className="f5-boundary"><ShieldCheck size={20} /><div><strong>普通主导航没有这些入口</strong><p>课程、组织与 SFT 项目均通过列表合同恢复；没有对象或权限时入口保持关闭并说明原因。</p></div></section>
    <div className="f5-capability-grid">{capabilities.map(({ icon: Icon, ...item }) => item.href ? <Link href={item.href} className="f5-capability-card" key={item.title}><div><span>{item.tier}</span><small>{item.gate}</small></div><Icon size={23} /><h2>{item.title}</h2><p>{item.text}</p><b>进入受控验收 <ArrowRight size={15} /></b></Link> : <article className="f5-capability-card is-disabled" key={item.title}><div><span>{item.tier}</span><small>{item.gate}</small></div><Icon size={23} /><h2>{item.title}</h2><p>{item.text}</p>{!isContractMock && item.title === "组织与班级聚合" ? <button className="button button-secondary" onClick={() => createOrganization.mutate()} disabled={createOrganization.isPending}>{createOrganization.isPending ? "创建中…" : "创建学习组织"}</button> : !isContractMock && item.title === "SFT 五重门" ? <button className="button button-secondary" onClick={() => createSftProject.mutate()} disabled={createSftProject.isPending}>{createSftProject.isPending ? "创建中…" : "创建 SFT 项目"}</button> : <b>需要先创建对应对象</b>}</article>)}</div>
    {createOrganization.error || createSftProject.error ? <Notice tone="error" {...presentError(createOrganization.error ?? createSftProject.error)} /> : null}
  </F5Shell>;
}
