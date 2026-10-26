"use client";

import { BookOpenCheck, Building2, ShieldAlert, UserPlus, UsersRound } from "lucide-react";
import { useParams } from "next/navigation";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { LoadingCard, Notice } from "@/components/Feedback";
import { F5Shell } from "@/components/controlled/F5Shell";
import {
  courseAssignmentListSchema, genericRecordSchema, groupListSchema, groupSchema,
  organizationAggregateSchema, organizationMemberListSchema,
} from "@/features/controlled/schema";
import { courseListSchema } from "@/features/system/schema";
import { apiFetchContract, jsonBody, presentError } from "@/lib/api/client";
import { isContractMock } from "@/lib/runtime";

type Operation = "member" | "group" | "group-member" | "assignment";

export default function OrganizationPage() {
  const { organizationId } = useParams<{ organizationId: string }>();
  const client = useQueryClient();
  const [log, setLog] = useState<string[]>([]);
  const [permissionError, setPermissionError] = useState<unknown>(null);
  const [learnerId, setLearnerId] = useState(isContractMock ? "demo-learner-f5" : "");
  const [groupName, setGroupName] = useState(isContractMock ? "第二班" : "我的学习班级");
  const [createdGroupId, setCreatedGroupId] = useState<string | null>(null);

  const aggregate = useQuery({ queryKey: ["f5-org", organizationId], queryFn: () => apiFetchContract(organizationAggregateSchema, `/api/v1/organizations/${organizationId}/aggregate`) });
  const members = useQuery({ queryKey: ["organization-members", organizationId], queryFn: () => apiFetchContract(organizationMemberListSchema, `/api/v1/organizations/${organizationId}/members?limit=100`), enabled: !isContractMock });
  const groups = useQuery({ queryKey: ["organization-groups", organizationId], queryFn: () => apiFetchContract(groupListSchema, `/api/v1/organizations/${organizationId}/groups?limit=100`), enabled: !isContractMock });
  const courses = useQuery({ queryKey: ["courses"], queryFn: () => apiFetchContract(courseListSchema, "/api/v1/courses?limit=100") });
  const selectedGroupId = createdGroupId ?? groups.data?.[0]?.id ?? (isContractMock ? "group-f5" : null);
  const selectedCourseId = courses.data?.[0]?.id ?? (isContractMock ? "demo-course-f5" : null);
  const assignments = useQuery({ queryKey: ["group-assignments", selectedGroupId], queryFn: () => apiFetchContract(courseAssignmentListSchema, `/api/v1/groups/${selectedGroupId}/course-assignments?limit=100`), enabled: !isContractMock && Boolean(selectedGroupId) });

  const operate = useMutation({
    mutationFn: async (step: Operation) => {
      if (step === "member") {
        if (!learnerId.trim()) throw new Error("请填写已注册学习者的用户 ID");
        return apiFetchContract(genericRecordSchema, `/api/v1/organizations/${organizationId}/members`, { method: "POST", body: jsonBody({ user_id: learnerId.trim(), role: "learner" }) });
      }
      if (step === "group") return apiFetchContract(groupSchema, `/api/v1/organizations/${organizationId}/groups`, { method: "POST", body: jsonBody({ name: groupName.trim() }) });
      if (!selectedGroupId) throw new Error("请先创建一个班级");
      if (step === "group-member") {
        if (!learnerId.trim()) throw new Error("请填写已加入组织的学习者用户 ID");
        return apiFetchContract(genericRecordSchema, `/api/v1/groups/${selectedGroupId}/members`, { method: "POST", body: jsonBody({ user_id: learnerId.trim() }) });
      }
      if (!selectedCourseId) throw new Error("当前没有可以分配的课程");
      return apiFetchContract(genericRecordSchema, `/api/v1/groups/${selectedGroupId}/course-assignments`, { method: "POST", body: jsonBody({ course_id: selectedCourseId, due_at: null }) });
    },
    onSuccess: async (value, step) => {
      if (step === "group" && "id" in value && typeof value.id === "string") setCreatedGroupId(value.id);
      const labels: Record<Operation, string> = { member: "学习者已加入组织", group: `${groupName}已创建`, "group-member": `学习者已加入${groupName}`, assignment: `课程已分配给${groupName}` };
      setLog((old) => [...old, labels[step]]);
      await Promise.all([
        client.invalidateQueries({ queryKey: ["f5-org", organizationId] }),
        client.invalidateQueries({ queryKey: ["organization-members", organizationId] }),
        client.invalidateQueries({ queryKey: ["organization-groups", organizationId] }),
        client.invalidateQueries({ queryKey: ["group-assignments"] }),
      ]);
    },
  });

  async function denied() {
    setPermissionError(null);
    try { await apiFetchContract(organizationAggregateSchema, "/api/v1/organizations/organization-denied-f5/aggregate"); }
    catch (error) { setPermissionError(error); }
  }

  const cards = aggregate.data ? [["学习者", aggregate.data.learner_count], ["班级", aggregate.data.group_count], ["已分配课程", aggregate.data.assigned_course_count], ["完成复习", aggregate.data.completed_review_count], ["题目作答", aggregate.data.attempted_question_count]] : [];
  return <F5Shell eyebrow="F5 · P2 组织管理" title="管理学习进度，不查看学习原文" description="管理员可以组织成员、班级和课程分配，但看板只返回聚合数量。前端和后端都不应把学习笔记、回答或 Tutor 对话暴露给组织管理者。" gate="organization" backHref="/controlled">
    <section className="f5-admin-role"><Building2 size={22} /><div><strong>学习组织</strong><p>组织 ID：{organizationId}</p></div><span>当前权限：owner / admin 逐次校验</span>{isContractMock ? <button className="button button-secondary" onClick={denied}>验证学习者无权限</button> : null}</section>
    {permissionError ? <div className="f5-feedback"><Notice tone="error" {...presentError(permissionError)} /></div> : null}
    {aggregate.isPending ? <LoadingCard label="正在读取组织聚合指标…" /> : aggregate.error ? <Notice tone="error" {...presentError(aggregate.error)} /> : aggregate.data ? <><div className="f5-metric-grid">{cards.map(([label,value]) => <article key={label}><strong>{value}</strong><span>{label}</span></article>)}</div><div className="f5-privacy-pass"><ShieldAlert size={18} /><div><strong>原始学习内容：未包含</strong><p>`raw_learning_content_included = false`，页面仅呈现聚合数量。</p></div></div></> : null}
    <section className="f5-admin-actions">
      <div><p className="eyebrow">受控编排</p><h2>每一步都使用真实用户、班级和课程 ID</h2></div>
      {!isContractMock ? <div className="f5-two-grid"><label className="field"><span>已注册学习者的用户 ID</span><input className="input" value={learnerId} onChange={(event) => setLearnerId(event.target.value)} placeholder="请让对方先用邀请码登录一次，再填写其用户 ID" /></label><label className="field"><span>新班级名称</span><input className="input" value={groupName} onChange={(event) => setGroupName(event.target.value)} /></label></div> : null}
      <div className="f5-admin-buttons"><button className="button button-secondary" onClick={() => operate.mutate("member")} disabled={operate.isPending || !learnerId.trim()}><UserPlus size={15} />{isContractMock ? "添加演示学习者" : "将学习者加入组织"}</button><button className="button button-secondary" onClick={() => operate.mutate("group")} disabled={operate.isPending || !groupName.trim()}><UsersRound size={15} />{isContractMock ? "创建第二班" : "创建班级"}</button><button className="button button-secondary" onClick={() => operate.mutate("group-member")} disabled={operate.isPending || !learnerId.trim() || !selectedGroupId}>加入{isContractMock ? "第二班" : "所选班级"}</button><button className="button button-primary" onClick={() => operate.mutate("assignment")} disabled={operate.isPending || !selectedGroupId || !selectedCourseId}><BookOpenCheck size={15} />分配{isContractMock ? "演示课程" : "当前课程"}</button></div>
    </section>
    {operate.error ? <Notice tone="error" {...presentError(operate.error)} /> : null}{log.length ? <ol className="f5-operation-log">{log.map((item,index) => <li key={`${item}-${index}`}>{item}</li>)}</ol> : null}
    {!isContractMock ? <p className="f5-contract-limit">真实恢复：{members.data?.length ?? 0} 名组织成员、{groups.data?.length ?? 0} 个班级、{assignments.data?.length ?? 0} 条当前班级课程分配。用户不存在、不是管理员或课程不属于当前账号时，后端会明确拒绝。</p> : <p className="f5-contract-limit">合同 Mock 仅用于验证权限和聚合边界；正式联调不会使用演示资源 ID。</p>}
  </F5Shell>;
}
