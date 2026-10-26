"use client";

import { AlertTriangle, ArrowRight, Check, ExternalLink, LockKeyhole, RefreshCw, RotateCcw, ShieldAlert, Unplug } from "lucide-react";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Notice } from "@/components/Feedback";
import { F5Shell, F5Status } from "@/components/controlled/F5Shell";
import { externalAuthorizationSchema, externalConnectionSchema, externalSyncConfirmationSchema, externalSyncSchema, type ExternalConnection, type ExternalSync, type ExternalSyncConfirmation } from "@/features/controlled/schema";
import { capabilitiesSchema } from "@/features/system/schema";
import { apiFetchContract, jsonBody, presentError } from "@/lib/api/client";
import { isContractMock } from "@/lib/runtime";

export default function ExternalCalendarPage() {
  const capabilities = useQuery({ queryKey: ["system-capabilities"], queryFn: () => apiFetchContract(capabilitiesSchema, "/api/v1/capabilities") });
  const provider = capabilities.data?.providers.external_calendar;
  const [authorization, setAuthorization] = useState<null | { connection_id: string; authorization_url: string; scopes: string[] }>(null);
  const [connection, setConnection] = useState<ExternalConnection | null>(null);
  const [sync, setSync] = useState<ExternalSync | null>(null);
  const [confirmation, setConfirmation] = useState<ExternalSyncConfirmation | null>(null);
  const [busy, setBusy] = useState(""); const [message, setMessage] = useState(""); const [caught, setCaught] = useState<unknown>(null);

  async function run(name: string, operation: () => Promise<void>) { setBusy(name); setCaught(null); setMessage(""); try { await operation(); } catch (error) { setCaught(error); } finally { setBusy(""); } }
  const authorize = (providerName = isContractMock ? "mock" : provider?.provider ?? "disabled") => run("authorize", async () => { const value = await apiFetchContract(externalAuthorizationSchema, "/api/v1/external-calendar/connections/authorization", { method: "POST", body: jsonBody({ provider: providerName }) }); setAuthorization(value); });
  const callback = () => run("callback", async () => { if (!authorization) return; const oauthState = new URL(authorization.authorization_url).searchParams.get("state") ?? ""; const value = await apiFetchContract(externalConnectionSchema, `/api/v1/external-calendar/connections/${authorization.connection_id}/callback`, { method: "POST", body: jsonBody({ code: "mock-code", state: oauthState }) }); setConnection(value); setMessage("演示授权已完成；令牌只保存在后端，浏览器不会读取。") });
  const propose = () => run("propose", async () => { const value = await apiFetchContract(externalSyncSchema, "/api/v1/external-calendar/syncs", { method: "POST", body: jsonBody({ connection_id: connection?.id, calendar_event_id: "calendar-event-f5" }) }); setSync(value); setConfirmation(null); });
  const preview = () => run("preview", async () => { const value = await apiFetchContract(externalSyncConfirmationSchema, `/api/v1/external-calendar/syncs/${sync?.id}/confirmation`, { method: "POST" }); setConfirmation(value); });
  const confirm = () => run("confirm", async () => { const value = await apiFetchContract(externalSyncSchema, `/api/v1/external-calendar/syncs/${sync?.id}/confirm`, { method: "POST", headers: { "If-Match": String(sync?.version), "X-Confirmation-Token": confirmation?.confirmation_token ?? "" } }); setSync(value); setConfirmation(null); setMessage(value.direction === "push" ? "已按本次确认写入外部日历。" : "已按本次确认把外部变更应用到内部日历。") });
  const refresh = () => run("refresh", async () => { const value = await apiFetchContract(externalSyncSchema, `/api/v1/external-calendar/syncs/${sync?.id}/refresh`, { method: "POST" }); setSync(value); setConfirmation(null); setMessage("检测到外部时间变化；尚未应用到内部日历。") });
  const revokeSync = () => run("revoke-sync", async () => { const value = await apiFetchContract(externalSyncSchema, `/api/v1/external-calendar/syncs/${sync?.id}`, { method: "DELETE" }); setSync(value); setConfirmation(null); setMessage("外部同步已撤销，历史状态保留。") });
  const disconnect = () => run("disconnect", async () => { const value = await apiFetchContract(externalConnectionSchema, `/api/v1/external-calendar/connections/${connection?.id}`, { method: "DELETE" }); setConnection(value); setMessage("日历授权已撤销，后端令牌已清空。") });
  const simulate = (kind: "expired" | "conflict" | "repeated") => run(kind, async () => { await apiFetchContract(externalSyncSchema, `/api/v1/external-calendar/syncs/${sync?.id}/confirm`, { method: "POST", headers: { "If-Match": String(kind === "conflict" ? Math.max(0, (sync?.version ?? 1) - 1) : sync?.version), "X-Confirmation-Token": kind === "expired" ? "expired-external-token" : kind === "repeated" ? `external-confirm-v${Math.max(1, (sync?.version ?? 2) - 1)}` : confirmation?.confirmation_token ?? "stale" } }); });

  return <F5Shell eyebrow="F5 · P1 外部能力" title="每一次外部写入，都重新问你" description="连接账号不等于授权写入。OAuth 只建立连接；每次推送或拉取都先形成提案、展示影响，再用当前版本的一次性凭证确认。" gate="external_calendar" backHref="/controlled">
    <section className="f5-boundary"><LockKeyhole size={19} /><div><strong>Provider、HTTPS、逐次确认缺一不可</strong><p>{isContractMock ? "当前是合同 Mock Provider，用于验证授权与确认规则。" : provider?.configured ? `当前已配置 ${provider.provider} Provider。` : "当前真实后端未配置外部日历 Provider，因此不会显示假授权或假同步成功。"}</p></div><button className="button button-secondary" onClick={() => authorize("disabled")}>验证未配置状态</button></section>
    {caught ? <div className="f5-feedback"><Notice tone="error" {...presentError(caught)} /></div> : null}{message ? <div className="f5-feedback"><Notice tone="success" message={message} /></div> : null}
    {!isContractMock && capabilities.isPending ? <Notice tone="info" message="正在读取外部日历配置…" /> : null}
    {!isContractMock && capabilities.data && !provider?.configured ? <Notice tone="info" message="外部日历暂不可用" detail="这属于真实 Provider 未配置状态。当前阶段仍可使用系统内部日历；待部署阶段提供外部日历供应商配置后再开放 OAuth 与逐次写入确认。" /> : null}
    {isContractMock || provider?.configured ? <>
    <ol className="f5-stepper">
      <li className={authorization ? "done" : "active"}><span>1</span><div><strong>请求 OAuth 权限</strong><p>只申请读取和写入日历事件，不读取联系人或邮件。</p></div>{!authorization ? <button className="button button-primary" onClick={() => authorize()} disabled={Boolean(busy)}>查看授权范围 <ArrowRight size={15} /></button> : <F5Status value="active" />}</li>
      <li className={connection?.status === "active" ? "done" : authorization ? "active" : ""}><span>2</span><div><strong>用户完成授权</strong>{authorization ? <p>权限：{authorization.scopes.join("、")}</p> : <p>等待上一步。</p>}</div>{authorization && !connection ? <button className="button button-primary" onClick={callback} disabled={Boolean(busy)}><ExternalLink size={15} />完成演示授权</button> : connection ? <F5Status value={connection.status} /> : null}</li>
      <li className={sync ? "done" : connection?.status === "active" ? "active" : ""}><span>3</span><div><strong>提出同步，不立即写入</strong><p>目标：内部事件“链式法则复习”。</p></div>{connection?.status === "active" && !sync ? <button className="button button-primary" onClick={propose} disabled={Boolean(busy)}>创建外部同步提案</button> : sync ? <F5Status value={sync.status} /> : null}</li>
      <li className={sync?.status === "synced" ? "done" : sync ? "active" : ""}><span>4</span><div><strong>查看影响并逐次确认</strong><p>{sync?.direction === "pull" ? "外部变化不会自动覆盖内部时间。" : "连接成功也不能跳过本次写入确认。"}</p></div>{sync && sync.status !== "synced" && sync.status !== "cancelled" ? <button className="button button-primary" onClick={preview} disabled={Boolean(busy)}><ShieldAlert size={15} />查看本次影响</button> : sync?.status === "synced" ? <F5Status value="synced" /> : null}</li>
    </ol>
    {confirmation ? <section className="f5-impact"><div><p className="eyebrow">一次性影响预览</p><h2>{confirmation.impact.direction === "push" ? "将写入外部日历" : "将更新内部日历"}</h2></div><dl><div><dt>方向</dt><dd>{confirmation.impact.direction}</dd></div><div><dt>外部写入</dt><dd>{confirmation.impact.will_write_external_calendar ? "是" : "否"}</dd></div><div><dt>内部更新</dt><dd>{confirmation.impact.will_update_internal_calendar ? "是" : "否"}</dd></div><div><dt>可撤销</dt><dd>{confirmation.impact.can_undo ? "是" : "否"}</dd></div></dl><pre>{JSON.stringify(confirmation.impact.pending_change, null, 2)}</pre><button className="button button-primary" onClick={confirm} disabled={Boolean(busy)}><Check size={16} />确认本次同步</button></section> : null}
    {sync?.status === "synced" ? <div className="f5-action-row"><button className="button button-secondary" onClick={refresh}><RefreshCw size={15} />检查外部变化</button><button className="button button-secondary" onClick={revokeSync}><RotateCcw size={15} />撤销外部同步</button><button className="button button-secondary" onClick={disconnect}><Unplug size={15} />撤销账号授权</button></div> : null}
    {sync && sync.status !== "cancelled" ? <details className="f5-diagnostics"><summary>异常保护验证{isContractMock ? "（仅合同 Mock）" : ""}</summary><p><AlertTriangle size={14} />故意发送过期、重复凭证或旧版本，预期被拒绝且不显示同步成功。</p><div className="cluster"><button className="button button-secondary" onClick={() => simulate("expired")}>模拟确认过期</button><button className="button button-secondary" onClick={() => simulate("conflict")}>模拟版本冲突</button>{sync.status === "synced" ? <button className="button button-secondary" onClick={() => simulate("repeated")}>模拟重复确认</button> : null}</div></details> : null}
    </> : null}
  </F5Shell>;
}
