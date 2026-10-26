import { delay, http, HttpResponse } from "msw";
import { z } from "zod";

const COURSE_ID = "demo-course-f4";
const PLAN_ID = "plan-f4";
const CANDIDATE_ID = "candidate-f4";
const fixedNow = "2026-09-01T14:30:00+08:00";

type Candidate = {
  id: string; ordinal: number; start_at: string; end_at: string; timezone: string; reason: string;
  confidence: number; status: string; source_kind: string; version: number; created_at: string; updated_at: string;
};
type CalendarEvent = {
  id: string; candidate_id: string; plan_id: string; course_id: string; title: string; action_type: string;
  target_id: string; start_at: string; end_at: string; timezone: string; status: string; version: number;
  created_at: string; updated_at: string; cancelled_at: string | null; completed_at: string | null;
};

let sequence = 0;
const nextId = (prefix: string) => `${prefix}-f4-${++sequence}`;

function initialCandidate(): Candidate {
  return {
    id: CANDIDATE_ID, ordinal: 1, start_at: "2026-09-02T19:30:00+08:00", end_at: "2026-09-02T20:00:00+08:00",
    timezone: "Asia/Shanghai", reason: "晚饭后是你设置的可用时段，30 分钟足够完成一次回忆与检验。",
    confidence: 0.91, status: "proposed", source_kind: "preference_rule", version: 1, created_at: fixedNow, updated_at: fixedNow,
  };
}

const state: {
  planCreated: boolean;
  planStatus: string;
  candidate: Candidate;
  confirmation: { token: string; expectedVersion: number; used: boolean } | null;
  events: CalendarEvent[];
  actionEvents: { id: string; plan_id: string; event_type: "started" | "skipped" | "completed"; reason: string | null; created_at: string }[];
  preference: Record<string, unknown> | null;
  notification: { id: string; course_id: string; enabled: boolean; channel: "in_app" | "webhook"; lead_minutes: number; version: number; created_at: string; updated_at: string };
  deliveries: Record<string, unknown>[];
  feedback: Record<string, unknown>[];
} = {
  planCreated: false,
  planStatus: "ready",
  candidate: initialCandidate(),
  confirmation: null,
  events: [],
  actionEvents: [],
  preference: null,
  notification: { id: "notification-preference-f4", course_id: COURSE_ID, enabled: true, channel: "in_app", lead_minutes: 30, version: 1, created_at: fixedNow, updated_at: fixedNow },
  deliveries: [],
  feedback: [],
};

export function resetF4MockState() {
  sequence = 0;
  state.planCreated = false;
  state.planStatus = "ready";
  state.candidate = initialCandidate();
  state.confirmation = null;
  state.events = [];
  state.actionEvents = [];
  state.preference = null;
  state.notification = { id: "notification-preference-f4", course_id: COURSE_ID, enabled: true, channel: "in_app", lead_minutes: 30, version: 1, created_at: fixedNow, updated_at: fixedNow };
  state.deliveries = [];
  state.feedback = [];
}

function error(code: string, message: string, status = 409) {
  return HttpResponse.json({ error: { code, message, request_id: `mock-${code.toLowerCase()}` } }, { status });
}

function planResponse() {
  return {
    id: PLAN_ID, course_id: COURSE_ID, status: state.planStatus, version: 1,
    next_action: { type: "note_review", target_id: "note-f3", reason: "先闭卷回忆链式法则，再用错题检验薄弱点。", duration_min: 30, plan_id: PLAN_ID },
    calendar_candidates: [state.candidate], assumptions: ["默认使用 Asia/Shanghai 时区", "未连接外部日历，不读取私人日程"],
    conflicts: [], requires_confirmation: state.candidate.status !== "confirmed", prompt_version: "BL-PLAN-v1.0.0",
    requested_model_id: "deepseek-chat", returned_model_id: "contract-mock-f4", fallback_reason: null,
    error_code: null, error_message: null, created_at: fixedNow, updated_at: state.candidate.updated_at,
  };
}

function currentVersion(request: Request) {
  return Number(request.headers.get("If-Match"));
}

export const f4Handlers = [
  http.post("/api/v1/auth/invite-session", async ({ request }) => {
    const body = z.object({ invite_code: z.string() }).safeParse(await request.clone().json());
    if (!body.success || body.data.invite_code !== "F4-DEMO-2026") return;
    resetF4MockState();
    return HttpResponse.json({ user: { id: "demo-user-f4", status: "active" }, expires_at: fixedNow });
  }),

  http.get(`/api/v1/courses/${COURSE_ID}/workspace`, async () => {
    await delay(100);
    const event = state.events.find((item) => item.status === "scheduled");
    return HttpResponse.json({
      course_id: COURSE_ID,
      action: event
        ? { type: "note_review", target_id: event.target_id, reason: "复习时间已经由你确认。到点后先做闭卷回忆，再查看结构化笔记。", duration_min: 30, plan_id: PLAN_ID }
        : { type: "generate_review_plan", target_id: "snapshot-plan-f4", reason: "材料与学习闭环已经就绪，现在把下一次复习安排成一个可确认的行动。", duration_min: 5, plan_id: state.planCreated ? PLAN_ID : null },
      derived_by: "workflow",
    });
  }),

  http.post(`/api/v1/courses/${COURSE_ID}/review-plans`, async ({ request }) => {
    await delay(180);
    if (!request.headers.get("Idempotency-Key")) return error("IDEMPOTENCY_KEY_REQUIRED", "缺少幂等键。", 422);
    z.object({ timezone: z.string().optional(), time_expression: z.string().optional() }).parse(await request.json());
    state.planCreated = true;
    return HttpResponse.json({ plan: planResponse(), task_id: "task-plan-f4" }, { status: 202 });
  }),

  http.get(`/api/v1/review-plans/${PLAN_ID}`, async () => {
    await delay(90);
    return state.planCreated ? HttpResponse.json(planResponse()) : error("PLAN_NOT_FOUND", "还没有生成复习计划。", 404);
  }),

  http.post(`/api/v1/review-plans/${PLAN_ID}/action-events`, async ({ request }) => {
    await delay(80);
    const body = z.object({ event_type: z.enum(["started", "skipped", "completed"]), reason: z.string().nullable().optional() }).parse(await request.json());
    const item = { id: nextId("action"), plan_id: PLAN_ID, event_type: body.event_type, reason: body.reason ?? null, created_at: fixedNow };
    state.actionEvents.push(item);
    if (body.event_type === "completed") state.planStatus = "completed";
    return HttpResponse.json(item, { status: 201 });
  }),

  http.patch(`/api/v1/calendar-candidates/${CANDIDATE_ID}`, async ({ request }) => {
    await delay(110);
    if (currentVersion(request) !== state.candidate.version) return error("VERSION_CONFLICT", "候选时间已经变化，请刷新后重新预览影响。", 409);
    const body = z.object({ start_at: z.string(), end_at: z.string(), timezone: z.string() }).parse(await request.json());
    state.candidate = { ...state.candidate, ...body, status: "deferred", version: state.candidate.version + 1, updated_at: fixedNow };
    state.confirmation = null;
    return HttpResponse.json(state.candidate);
  }),

  http.post(`/api/v1/calendar-candidates/${CANDIDATE_ID}/reject`, async ({ request }) => {
    await delay(80);
    if (currentVersion(request) !== state.candidate.version) return error("VERSION_CONFLICT", "候选时间已经变化，请刷新后重试。", 409);
    state.candidate = { ...state.candidate, status: "rejected", version: state.candidate.version + 1, updated_at: fixedNow };
    state.confirmation = null;
    return HttpResponse.json(state.candidate);
  }),

  http.post(`/api/v1/calendar-candidates/${CANDIDATE_ID}/confirmation-preview`, async ({ request }) => {
    await delay(100);
    if (currentVersion(request) !== state.candidate.version) return error("VERSION_CONFLICT", "候选时间版本已变化，无法生成确认预览。", 409);
    if (state.candidate.status === "rejected") return error("CANDIDATE_REJECTED", "该候选时间已拒绝。", 409);
    const token = `confirm-token-v${state.candidate.version}`;
    state.confirmation = { token, expectedVersion: state.candidate.version, used: false };
    return HttpResponse.json({
      confirmation_id: nextId("confirmation"), confirmation_token: token, expires_at: "2026-09-01T14:40:00+08:00",
      candidate_id: CANDIDATE_ID, expected_version: state.candidate.version,
      impact: {
        will_create_internal_event: true, will_write_external_calendar: false,
        will_queue_notification: state.notification.enabled, event_title: "链式法则 · 闭卷回忆与错题检验",
        start_at: state.candidate.start_at, end_at: state.candidate.end_at, timezone: state.candidate.timezone,
      },
    });
  }),

  http.post(`/api/v1/calendar-candidates/${CANDIDATE_ID}/confirm`, async ({ request }) => {
    await delay(120);
    const body = z.object({ confirmation_token: z.string() }).parse(await request.json());
    if (body.confirmation_token === "expired-f4-token") return error("CONFIRMATION_EXPIRED", "确认已过期，请重新查看影响。", 410);
    if (currentVersion(request) !== state.candidate.version) return error("VERSION_CONFLICT", "候选时间已经变化，请重新查看影响。", 409);
    if (!state.confirmation || body.confirmation_token !== state.confirmation.token) return error("CONFIRMATION_INVALID", "确认令牌无效，请重新查看影响。", 409);
    if (state.confirmation.used) return error("CONFIRMATION_ALREADY_USED", "这次确认已经使用过，日历不会重复写入。", 409);
    if (state.confirmation.expectedVersion !== state.candidate.version) return error("VERSION_CONFLICT", "预览对应的版本已经失效。", 409);
    state.confirmation.used = true;
    state.candidate = { ...state.candidate, status: "confirmed", version: state.candidate.version + 1, updated_at: fixedNow };
    const existing = state.events[0];
    if (existing) return HttpResponse.json(existing, { status: 201 });
    const event: CalendarEvent = {
      id: "calendar-event-f4", candidate_id: CANDIDATE_ID, plan_id: PLAN_ID, course_id: COURSE_ID,
      title: "链式法则 · 闭卷回忆与错题检验", action_type: "note_review", target_id: "note-f3",
      start_at: state.candidate.start_at, end_at: state.candidate.end_at, timezone: state.candidate.timezone,
      status: "scheduled", version: 1, created_at: fixedNow, updated_at: fixedNow, cancelled_at: null, completed_at: null,
    };
    state.events.push(event);
    if (state.notification.enabled) state.deliveries.push({
      id: "delivery-f4", course_id: COURSE_ID, calendar_event_id: event.id, channel: "in_app", template_id: "review-reminder-v1",
      status: "queued", scheduled_at: "2026-09-02T19:00:00+08:00", delivered_at: null, error_code: null, created_at: fixedNow,
    });
    return HttpResponse.json(event, { status: 201 });
  }),

  http.get(`/api/v1/courses/${COURSE_ID}/calendar-events`, async () => {
    await delay(70);
    return HttpResponse.json(state.events);
  }),

  http.post(/\/api\/v1\/calendar-events\/(calendar-event-f4)\/(undo|complete)$/, async ({ params, request }) => {
    await delay(90);
    const event = state.events[0];
    if (!event) return error("CALENDAR_EVENT_NOT_FOUND", "内部日历事件不存在。", 404);
    if (currentVersion(request) !== event.version) return error("VERSION_CONFLICT", "日历事件已经变化，请刷新后重试。", 409);
    const operation = String(params["1"] ?? "");
    if (operation === "undo") {
      event.status = "cancelled"; event.cancelled_at = fixedNow;
    } else {
      event.status = "completed"; event.completed_at = fixedNow; state.planStatus = "completed";
    }
    event.version += 1; event.updated_at = fixedNow;
    return HttpResponse.json(event);
  }),

  http.get(`/api/v1/calendar-events/calendar-event-f4.ics`, () => new HttpResponse(
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:calendar-event-f4\r\nSUMMARY:链式法则 · 闭卷回忆与错题检验\r\nDTSTART:20260902T113000Z\r\nDTEND:20260902T120000Z\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n",
    { headers: { "Content-Type": "text/calendar; charset=utf-8", "Content-Disposition": "attachment; filename=review-plan.ics" } },
  )),

  http.put(`/api/v1/courses/${COURSE_ID}/study-preference`, async ({ request }) => {
    await delay(90);
    const expected = currentVersion(request);
    const existingVersion = Number(state.preference?.version ?? 0);
    if (expected !== existingVersion) return error("VERSION_CONFLICT", "学习偏好已变化，请刷新后重试。", 409);
    const body = z.object({ timezone: z.string(), available_time: z.array(z.object({ weekday: z.number(), start: z.string(), end: z.string() })), preferred_duration_min: z.number() }).parse(await request.json());
    state.preference = { id: "study-preference-f4", course_id: COURSE_ID, ...body, version: existingVersion + 1, created_at: fixedNow, updated_at: fixedNow };
    return HttpResponse.json(state.preference);
  }),
  http.get(`/api/v1/courses/${COURSE_ID}/study-preference`, async () => {
    await delay(60);
    return state.preference
      ? HttpResponse.json(state.preference)
      : error("STUDY_PREFERENCE_NOT_FOUND", "还没有保存学习偏好。", 404);
  }),

  http.get(`/api/v1/courses/${COURSE_ID}/notification-preference`, async () => {
    await delay(60);
    return HttpResponse.json(state.notification);
  }),
  http.put(`/api/v1/courses/${COURSE_ID}/notification-preference`, async ({ request }) => {
    await delay(80);
    const body = z.object({ enabled: z.boolean(), channel: z.enum(["in_app", "webhook"]), lead_minutes: z.number(), expected_version: z.number().nullable().optional() }).parse(await request.json());
    if (body.channel === "webhook") return error("NOTIFICATION_PROVIDER_UNAVAILABLE", "Webhook 通知供应商尚未启用。", 409);
    if (body.expected_version !== state.notification.version) return error("VERSION_CONFLICT", "通知偏好已经变化，请刷新后重试。", 409);
    state.notification = { ...state.notification, enabled: body.enabled, channel: body.channel, lead_minutes: body.lead_minutes, version: state.notification.version + 1, updated_at: fixedNow };
    if (!body.enabled) state.deliveries = state.deliveries.map((item) => item.status === "queued" ? { ...item, status: "cancelled", error_code: "NOTIFICATION_PREFERENCE_CHANGED" } : item);
    return HttpResponse.json(state.notification);
  }),
  http.get(`/api/v1/courses/${COURSE_ID}/notification-deliveries`, async () => HttpResponse.json(state.deliveries)),
  http.delete(/\/api\/v1\/notification-deliveries\/(.+)$/, async ({ params }) => {
    const id = String(params["0"] ?? "");
    const delivery = state.deliveries.find((item) => item.id === id);
    if (!delivery) return error("NOT_FOUND", "通知记录不存在。", 404);
    if (delivery.status !== "queued") return error("DELIVERY_NOT_CANCELLABLE", "只有等待中的通知可以取消。", 409);
    delivery.status = "cancelled";
    return new HttpResponse(null, { status: 204 });
  }),

  http.get(`/api/v1/courses/${COURSE_ID}/feedback`, async () => HttpResponse.json(state.feedback)),
  http.post("/api/v1/feedback", async ({ request }) => {
    const body = z.object({ course_id: z.string(), target_type: z.string(), target_id: z.string(), target_version_id: z.string().nullable().optional(), action: z.enum(["report", "hide", "correct"]), reason_code: z.string(), detail: z.string().nullable().optional(), correction: z.record(z.string(), z.unknown()).optional() }).parse(await request.json());
    const item = { id: nextId("feedback"), ...body, target_version_id: body.target_version_id ?? null, detail: body.detail ?? null, correction: body.correction ?? {}, status: "open", resolution_note: null, version: 1, created_at: fixedNow, updated_at: fixedNow };
    state.feedback.unshift(item);
    return HttpResponse.json(item, { status: 201 });
  }),
  http.delete(/\/api\/v1\/feedback\/(.+)$/, async ({ params, request }) => {
    const item = state.feedback.find((feedback) => feedback.id === String(params["0"] ?? ""));
    if (!item) return error("NOT_FOUND", "反馈不存在。", 404);
    if (currentVersion(request) !== item.version) return error("VERSION_CONFLICT", "反馈状态已经变化。", 409);
    item.status = "revoked"; item.version = Number(item.version) + 1; item.updated_at = fixedNow;
    return HttpResponse.json(item);
  }),

  http.get("/api/v1/workflow-runs/run-plan-f4", async () => HttpResponse.json({
    id: "run-plan-f4", task_type: "review_plan_generation", course_id: COURSE_ID, status: "completed",
    scope_snapshot: { material_count: 3, context_snapshot_id: "snapshot-plan-f4", raw_material_text: "[REDACTED]", secret_fields_removed: true },
    policy_versions: { planning: "plan-policy-v1", confirmation: "one-time-v1", privacy: "redaction-v2" },
    started_at: "2026-09-01T14:29:20+08:00", finished_at: fixedNow,
    events: [
      { id: "run-event-1", event_type: "scope_locked", message: "已冻结本次材料范围。", created_at: "2026-09-01T14:29:20+08:00" },
      { id: "run-event-2", event_type: "candidate_generated", message: "已生成 1 个可确认候选时间。", created_at: fixedNow },
    ],
    jobs: [{ id: "job-plan-f4", job_type: "review_plan_generation", status: "completed" }],
  })),
];
