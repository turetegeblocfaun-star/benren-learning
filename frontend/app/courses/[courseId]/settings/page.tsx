"use client";

import { Bell, BellOff, CalendarCog, Check, Info, MessageSquareWarning, Send, ShieldOff, Trash2 } from "lucide-react";
import { useParams } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { LoadingCard, Notice } from "@/components/Feedback";
import { F4Shell, StateLabel, formatPlanTime } from "@/components/planning/F4Shell";
import {
  feedbackListSchema,
  feedbackSchema,
  notificationDeliveriesSchema,
  notificationPreferenceSchema,
  studyPreferenceSchema,
} from "@/features/planning/schema";
import { apiFetch, apiFetchContract, AppError, idempotencyKey, jsonBody, presentError } from "@/lib/api/client";

const weekdayLabels = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];

export default function PlanningSettingsPage() {
  const { courseId } = useParams<{ courseId: string }>();
  const queryClient = useQueryClient();
  const [days, setDays] = useState([1, 3, 5]);
  const [start, setStart] = useState("19:30");
  const [end, setEnd] = useState("21:00");
  const [duration, setDuration] = useState(30);
  const [preferenceVersion, setPreferenceVersion] = useState(0);
  const [prefMessage, setPrefMessage] = useState("");
  const [notificationEnabled, setNotificationEnabled] = useState(true);
  const [leadMinutes, setLeadMinutes] = useState(30);
  const [notificationMessage, setNotificationMessage] = useState("");
  const [feedbackDetail, setFeedbackDetail] = useState("");
  const [feedbackMessage, setFeedbackMessage] = useState("");

  const preference = useQuery({ queryKey: ["study-preference", courseId], queryFn: () => apiFetchContract(studyPreferenceSchema, `/api/v1/courses/${courseId}/study-preference`), retry: false });
  const notification = useQuery({ queryKey: ["f4-notification", courseId], queryFn: () => apiFetchContract(notificationPreferenceSchema, `/api/v1/courses/${courseId}/notification-preference`), retry: false });
  const deliveries = useQuery({ queryKey: ["f4-deliveries", courseId], queryFn: () => apiFetchContract(notificationDeliveriesSchema, `/api/v1/courses/${courseId}/notification-deliveries`) });
  const feedback = useQuery({ queryKey: ["f4-feedback", courseId], queryFn: () => apiFetchContract(feedbackListSchema, `/api/v1/courses/${courseId}/feedback`) });

  useEffect(() => {
    if (preference.data) {
      const first = preference.data.available_time[0];
      setDays(preference.data.available_time.map((item) => item.weekday));
      if (first) {
        setStart(first.start);
        setEnd(first.end);
      }
      setDuration(preference.data.preferred_duration_min);
      setPreferenceVersion(preference.data.version);
    }
  }, [preference.data]);

  useEffect(() => {
    if (notification.data) {
      setNotificationEnabled(notification.data.enabled);
      setLeadMinutes(notification.data.lead_minutes);
    }
  }, [notification.data]);

  const savePreference = useMutation({
    mutationFn: () => apiFetchContract(studyPreferenceSchema, `/api/v1/courses/${courseId}/study-preference`, {
      method: "PUT", headers: { "If-Match": String(preferenceVersion), "Idempotency-Key": idempotencyKey("study-preference") },
      body: jsonBody({ timezone: "Asia/Shanghai", available_time: days.map((weekday) => ({ weekday, start, end })), preferred_duration_min: duration }),
    }),
    onSuccess: (value) => {
      queryClient.setQueryData(["study-preference", courseId], value);
      setPreferenceVersion(value.version);
      setPrefMessage(`学习偏好已保存为 v${value.version}。新计划会使用这些时段，已有计划不会被静默改写。`);
    },
  });

  const saveNotification = useMutation({
    mutationFn: () => apiFetchContract(notificationPreferenceSchema, `/api/v1/courses/${courseId}/notification-preference`, {
      method: "PUT", headers: { "Idempotency-Key": idempotencyKey("notification-preference") },
      body: jsonBody({ enabled: notificationEnabled, channel: "in_app", lead_minutes: leadMinutes, expected_version: notification.data?.version ?? null }),
    }),
    onSuccess: async (value) => { setNotificationMessage(value.enabled ? `站内提醒已开启，将提前 ${value.lead_minutes} 分钟。` : "站内提醒已关闭；尚未发送的提醒会被取消并保留记录。"); await Promise.all([queryClient.invalidateQueries({ queryKey: ["f4-notification", courseId] }), queryClient.invalidateQueries({ queryKey: ["f4-deliveries", courseId] })]); },
  });

  const cancelDelivery = useMutation({
    mutationFn: (id: string) => apiFetch<void>(`/api/v1/notification-deliveries/${id}`, { method: "DELETE" }),
    onSuccess: async () => { setNotificationMessage("等待中的提醒已取消。"); await queryClient.invalidateQueries({ queryKey: ["f4-deliveries", courseId] }); },
  });

  const createFeedback = useMutation({
    mutationFn: () => apiFetchContract(feedbackSchema, "/api/v1/feedback", {
      method: "POST", headers: { "Idempotency-Key": idempotencyKey("feedback") },
      body: jsonBody({ course_id: courseId, target_type: "learning_asset", target_id: "note-f3", target_version_id: "note-version-f3-v1", action: "report", reason_code: "content_needs_review", detail: feedbackDetail, correction: {} }),
    }),
    onSuccess: async () => { setFeedbackDetail(""); setFeedbackMessage("反馈已提交并保留目标版本，不会直接覆盖学习内容。"); await queryClient.invalidateQueries({ queryKey: ["f4-feedback", courseId] }); },
  });

  const revokeFeedback = useMutation({
    mutationFn: ({ id, version }: { id: string; version: number }) => apiFetchContract(feedbackSchema, `/api/v1/feedback/${id}`, { method: "DELETE", headers: { "If-Match": String(version) } }),
    onSuccess: async () => { setFeedbackMessage("反馈已撤回，历史状态仍可追溯。"); await queryClient.invalidateQueries({ queryKey: ["f4-feedback", courseId] }); },
  });

  function submitPreference(event: FormEvent) { event.preventDefault(); setPrefMessage(""); savePreference.mutate(); }
  function submitNotification(event: FormEvent) { event.preventDefault(); setNotificationMessage(""); saveNotification.mutate(); }
  function toggleDay(day: number) { setDays((current) => current.includes(day) ? current.filter((item) => item !== day) : [...current, day].sort()); }
  const settingError = savePreference.error ?? saveNotification.error ?? cancelDelivery.error;
  const feedbackError = createFeedback.error ?? revokeFeedback.error;

  return (
    <F4Shell eyebrow="F4 · 偏好、通知与反馈" title="把可用时间和提醒边界说清楚" description="偏好只影响未来建议；站内通知可以关闭；任何反馈都绑定目标版本，不会直接改写原内容。" backHref={`/courses/${courseId}/workspace`}>
      <div className="f4-settings-grid">
        <section className="f4-card">
          <div className="f4-card-head"><div><p className="eyebrow">学习偏好</p><h2>什么时候适合安排复习</h2></div><CalendarCog size={22} /></div>
          <div className="f4-contract-note"><Info size={16} /><p><strong>设置会从后端恢复。</strong>刷新或换设备后仍读取最新版本；保存时继续使用版本校验，避免静默覆盖。</p></div>
          {preference.isPending ? <LoadingCard label="正在读取学习偏好…" /> : null}
          {preference.error instanceof AppError && preference.error.code === "STUDY_PREFERENCE_NOT_FOUND" ? <Notice tone="info" message="还没有保存学习偏好，下面显示的是建议初始值。" /> : preference.error ? <Notice tone="error" {...presentError(preference.error)} /> : null}
          {prefMessage ? <Notice tone="success" message={prefMessage} /> : null}
          {savePreference.error ? <Notice tone="error" {...presentError(savePreference.error)} /> : null}
          <form className="f4-settings-form" onSubmit={submitPreference}>
            <fieldset><legend>可用星期</legend><div className="f4-day-picker">{weekdayLabels.map((label, day) => <button type="button" key={label} aria-pressed={days.includes(day)} onClick={() => toggleDay(day)}>{days.includes(day) ? <Check size={13} /> : null}{label}</button>)}</div></fieldset>
            <div className="f4-field-row"><label className="field"><span>开始</span><input className="input" type="time" value={start} onChange={(event) => setStart(event.target.value)} /></label><label className="field"><span>结束</span><input className="input" type="time" value={end} onChange={(event) => setEnd(event.target.value)} /></label><label className="field"><span>偏好时长（分钟）</span><input className="input" type="number" min={5} max={180} value={duration} onChange={(event) => setDuration(Number(event.target.value))} /></label></div>
            <div className="cluster f4-form-foot"><span>时区固定显示：Asia/Shanghai</span><button className="button button-primary" disabled={savePreference.isPending || days.length === 0}>{savePreference.isPending ? "保存中…" : "保存学习偏好"}</button></div>
          </form>
        </section>

        <section className="f4-card">
          <div className="f4-card-head"><div><p className="eyebrow">站内通知</p><h2>只在你允许时排队</h2></div>{notificationEnabled ? <Bell size={22} /> : <BellOff size={22} />}</div>
          {notification.isPending ? <LoadingCard label="正在读取通知偏好…" /> : notification.error ? <Notice tone="error" {...presentError(notification.error)} /> : (
            <form className="f4-settings-form" onSubmit={submitNotification}>
              {notificationMessage ? <Notice tone="success" message={notificationMessage} /> : null}
              {settingError && !savePreference.error ? <Notice tone="error" {...presentError(settingError)} /> : null}
              <label className="f4-toggle"><input type="checkbox" checked={notificationEnabled} onChange={(event) => setNotificationEnabled(event.target.checked)} /><span aria-hidden="true" /><div><strong>启用站内复习提醒</strong><small>关闭后，未来等待中的提醒会标记为取消。</small></div></label>
              <label className="field"><span>提前提醒（分钟）</span><input className="input" type="number" min={0} max={10080} value={leadMinutes} onChange={(event) => setLeadMinutes(Number(event.target.value))} /></label>
              <button className="button button-primary" disabled={saveNotification.isPending}>{saveNotification.isPending ? "保存中…" : "保存通知偏好"}</button>
            </form>
          )}
          <div className="f4-provider-off"><ShieldOff size={17} /><div><strong>Webhook 与外部通知未启用</strong><p>供应商未配置时后端会明确拒绝，不展示虚假的成功状态。</p></div></div>
        </section>
      </div>

      <section className="f4-section">
        <div className="f4-section-heading"><div><p className="eyebrow">通知账本</p><h2>等待、取消、失败都看得见</h2></div><p>只有确认内部日历事件后，才可能产生提醒记录。</p></div>
        {deliveries.isPending ? <LoadingCard label="正在读取通知记录…" /> : deliveries.error ? <Notice tone="error" {...presentError(deliveries.error)} /> : deliveries.data?.length === 0 ? <div className="f4-compact-empty"><BellOff size={19} />暂无通知记录；候选计划本身不会创建提醒。</div> : (
          <div className="f4-delivery-list">{deliveries.data?.map((delivery) => <article key={delivery.id}><div><StateLabel status={delivery.status} /><strong>复习提醒 · 站内</strong><span>{formatPlanTime(delivery.scheduled_at)}</span></div>{delivery.status === "queued" ? <button className="f4-danger-link" onClick={() => cancelDelivery.mutate(delivery.id)}><Trash2 size={14} />取消等待</button> : <small>{delivery.error_code === "NOTIFICATION_PREFERENCE_CHANGED" ? "因偏好变化而取消" : "状态已结束"}</small>}</article>)}</div>
        )}
      </section>

      <section className="f4-feedback-card">
        <div><p className="eyebrow">可信反馈</p><h2>指出问题，但不直接覆盖内容</h2><p>演示反馈固定绑定“结构化笔记 v1”。正式产品会从具体内容处带入目标与版本。</p></div>
        <form onSubmit={(event) => { event.preventDefault(); setFeedbackMessage(""); createFeedback.mutate(); }}>
          <label className="field"><span>哪里需要核对？</span><textarea className="input" value={feedbackDetail} onChange={(event) => setFeedbackDetail(event.target.value)} minLength={4} required placeholder="例如：第二段推导缺少内层导数的来源说明。" /></label>
          <button className="button button-primary" disabled={createFeedback.isPending || feedbackDetail.trim().length < 4}><Send size={15} />{createFeedback.isPending ? "提交中…" : "提交版本化反馈"}</button>
        </form>
        {feedbackMessage ? <Notice tone="success" message={feedbackMessage} /> : null}
        {feedbackError ? <Notice tone="error" {...presentError(feedbackError)} /> : null}
        {feedback.isPending ? <LoadingCard label="正在读取反馈记录…" /> : feedback.error ? <Notice tone="error" {...presentError(feedback.error)} /> : feedback.data?.length ? <div className="f4-feedback-list">{feedback.data.map((item) => <article key={item.id}><MessageSquareWarning size={17} /><div><div className="cluster"><StateLabel status={item.status} /><small>目标版本：{item.target_version_id}</small></div><p>{item.detail}</p></div>{item.status === "open" ? <button className="f4-danger-link" onClick={() => revokeFeedback.mutate({ id: item.id, version: item.version })}>撤回</button> : null}</article>)}</div> : <div className="f4-compact-empty">暂无反馈记录。</div>}
      </section>
    </F4Shell>
  );
}
