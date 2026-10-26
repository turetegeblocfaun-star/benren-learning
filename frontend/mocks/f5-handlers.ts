import { delay, http, HttpResponse } from "msw";
import { z } from "zod";

const COURSE_ID = "demo-course-f5";
const now = "2026-09-01T16:20:00+08:00";
const state = {
  subjectiveCount: 0,
  connection: null as null | { id: string; provider: string; status: string; scopes: string[]; external_account_ref: string | null; expires_at: string | null; version: number },
  sync: null as null | { id: string; connection_id: string; calendar_event_id: string; status: string; direction: string; pending_change: Record<string, unknown>; external_event_id: string | null; error_code: string | null; version: number },
  syncConfirmation: null as null | { token: string; version: number; used: boolean },
  org: { learners: 1, groups: 1, assignments: 1 },
  cross: null as null | { id: string; source_course_id: string; target_course_id: string; selected_source_ref_ids: string[]; purpose: string; status: string; version: number; created_at: string; revoked_at: string | null },
  sft: { consent: false, dataset: false, evaluation: false, launched: false },
};

export function resetF5MockState() {
  state.subjectiveCount = 0; state.connection = null; state.sync = null; state.syncConfirmation = null;
  state.org = { learners: 1, groups: 1, assignments: 1 }; state.cross = null;
  state.sft = { consent: false, dataset: false, evaluation: false, launched: false };
}

function error(code: string, message: string, status = 409) {
  return HttpResponse.json({ error: { code, message, request_id: `mock-${code.toLowerCase()}` } }, { status });
}
function gateReport() {
  return {
    baseline_residual_exists: true, authorized_dataset_ready: state.sft.dataset, minimum_authorized_records: 1,
    active_authorized_records: state.sft.dataset ? 1 : 0, independent_evaluation_ready: state.sft.evaluation,
    quality_target_passed: state.sft.evaluation, safety_passed: state.sft.evaluation, provider_configured: true,
    eligible_to_launch: state.sft.dataset && state.sft.evaluation,
  };
}
function sftProject() {
  return { id: "sft-project-f5", name: "Tutor 引导表达改进", use_case: "修复基线仍无法解决的引导表达问题", baseline_metric_name: "golden_set_pass_rate", baseline_score: .6, target_score: .85, status: state.sft.launched ? "training_submitted" : state.sft.consent ? "preparing" : "draft", provider_job_id: state.sft.launched ? "provider-job-redacted-f5" : null, gate_report: gateReport(), created_at: now, updated_at: now };
}

export const f5Handlers = [
  http.post("/api/v1/auth/invite-session", async ({ request }) => {
    const body = z.object({ invite_code: z.string() }).safeParse(await request.clone().json());
    if (!body.success || body.data.invite_code !== "F5-DEMO-2026") return;
    resetF5MockState();
    return HttpResponse.json({ user: { id: "demo-admin-f5", status: "active" }, expires_at: now });
  }),
  http.get(`/api/v1/courses/${COURSE_ID}/subjective-exercises`, async () =>
    HttpResponse.json([]),
  ),
  http.post(`/api/v1/courses/${COURSE_ID}/subjective-exercises`, async ({ request }) => {
    await delay(100); z.object({ context_snapshot_id: z.string(), focus: z.string().nullable().optional() }).parse(await request.json());
    return HttpResponse.json({ id: "subjective-f5", course_id: COURSE_ID, context_snapshot_id: "snapshot-f5", prompt: "请用自己的话解释：为什么链式法则必须乘以内层函数的变化率？", rubric: [
      { id: "concept", label: "概念关系", description: "说明外层变化与内层变化之间的关系。" },
      { id: "evidence", label: "材料依据", description: "用课堂例子支持自己的解释。" },
    ], source_ref_ids: ["source-f3-example"], status: "ready", model_id: "contract-mock-f5", prompt_version: "BL-SUBJECTIVE-v1", created_at: now }, { status: 201 });
  }),
  http.post("/api/v1/subjective-exercises/subjective-f5/assessments", async ({ request }) => {
    const body = z.object({ response_text: z.string(), rubric_ratings: z.array(z.object({ criterion_id: z.string(), rating: z.number(), evidence_note: z.string() })), reflection: z.string(), confidence: z.number() }).parse(await request.json());
    if (new Set(body.rubric_ratings.map((item) => item.criterion_id)).size !== 2) return error("RUBRIC_MISMATCH", "请对全部且仅对当前评分维度完成自评。", 422);
    state.subjectiveCount += 1;
    return HttpResponse.json({ id: "assessment-f5", exercise_id: "subjective-f5", ...body, automatic_correctness: null, created_at: now }, { status: 201 });
  }),
  http.get(`/api/v1/courses/${COURSE_ID}/adaptive-review`, async () => HttpResponse.json({ id: "adaptive-f5", course_id: COURSE_ID, interval_days: state.subjectiveCount ? 4 : 2, next_review_at: state.subjectiveCount ? "2026-09-05T19:30:00+08:00" : "2026-09-03T19:30:00+08:00", evidence: { objective_attempt_count: 3, wrongbook_open_count: 1, subjective_assessment_count: state.subjectiveCount, confidence: state.subjectiveCount ? 4 : null }, explanation: state.subjectiveCount ? "结合 3 次客观作答、1 个待复习错题和 1 次主观题自评，建议 4 天后复习。" : "仅根据 3 次客观作答和 1 个待复习错题，建议 2 天后复习；完成主观自评后会重新计算。", algorithm_version: "adaptive-rule-v1", updated_at: now })),

  http.post("/api/v1/external-calendar/connections/authorization", async ({ request }) => {
    const body = z.object({ provider: z.string() }).parse(await request.json());
    if (body.provider === "disabled") return error("EXTERNAL_CALENDAR_PROVIDER_UNAVAILABLE", "外部日历 Provider 尚未配置。", 409);
    state.connection = { id: "calendar-connection-f5", provider: "mock", status: "pending", scopes: ["calendar.events.write", "calendar.events.read"], external_account_ref: null, expires_at: null, version: 1 };
    return HttpResponse.json({ connection_id: state.connection.id, provider: "mock", authorization_url: "http://127.0.0.1/mock-calendar/authorize?state=oauth-state-f5", status: "pending", scopes: state.connection.scopes });
  }),
  http.post("/api/v1/external-calendar/connections/calendar-connection-f5/callback", async ({ request }) => {
    const body = z.object({ code: z.string(), state: z.string() }).parse(await request.json());
    if (body.state !== "oauth-state-f5") return error("OAUTH_STATE_INVALID", "授权状态无效，已阻止连接。", 400);
    if (!state.connection) return error("FORBIDDEN", "授权会话不存在。", 403);
    state.connection = { ...state.connection, status: "active", external_account_ref: "mock-calendar-user", expires_at: "2026-09-08T16:20:00+08:00", version: 2 };
    return HttpResponse.json(state.connection);
  }),
  http.delete("/api/v1/external-calendar/connections/calendar-connection-f5", async () => {
    if (!state.connection) return error("FORBIDDEN", "连接不存在。", 403);
    state.connection = { ...state.connection, status: "revoked", external_account_ref: null, version: state.connection.version + 1 };
    return HttpResponse.json(state.connection);
  }),
  http.post("/api/v1/external-calendar/syncs", async ({ request }) => {
    const body = z.object({ connection_id: z.string(), calendar_event_id: z.string() }).parse(await request.json());
    if (state.connection?.status !== "active") return error("FORBIDDEN", "日历连接不可用。", 403);
    state.sync = { id: "external-sync-f5", connection_id: body.connection_id, calendar_event_id: body.calendar_event_id, status: "proposed", direction: "push", pending_change: { title: "链式法则复习", start_at: "2026-09-02T19:30:00+08:00" }, external_event_id: null, error_code: null, version: 1 };
    return HttpResponse.json(state.sync, { status: 201 });
  }),
  http.post("/api/v1/external-calendar/syncs/external-sync-f5/confirmation", async () => {
    if (!state.sync) return error("FORBIDDEN", "同步提案不存在。", 403);
    const token = `external-confirm-v${state.sync.version}`; state.syncConfirmation = { token, version: state.sync.version, used: false };
    return HttpResponse.json({ confirmation_token: token, expires_at: "2026-09-01T16:30:00+08:00", impact: { direction: state.sync.direction, will_write_external_calendar: state.sync.direction === "push", will_update_internal_calendar: state.sync.direction === "pull", pending_change: state.sync.pending_change, can_undo: true } });
  }),
  http.post("/api/v1/external-calendar/syncs/external-sync-f5/confirm", async ({ request }) => {
    if (!state.sync) return error("FORBIDDEN", "同步提案不存在。", 403);
    const token = request.headers.get("X-Confirmation-Token"); const version = Number(request.headers.get("If-Match"));
    if (token === "expired-external-token") return error("CONFIRMATION_EXPIRED", "外部同步确认已过期，请重新预览影响。", 410);
    if (version !== state.sync.version) return error("VERSION_CONFLICT", "同步提案已经变化，请重新预览影响。", 409);
    if (!state.syncConfirmation || token !== state.syncConfirmation.token || state.syncConfirmation.used) return error("CONFIRMATION_INVALID", "确认无效或已经使用。", 400);
    state.syncConfirmation.used = true; state.sync.status = "synced"; state.sync.version += 1;
    if (state.sync.direction === "push") state.sync.external_event_id = "external-event-f5";
    state.sync.pending_change = {};
    return HttpResponse.json(state.sync);
  }),
  http.post("/api/v1/external-calendar/syncs/external-sync-f5/refresh", async () => {
    if (!state.sync?.external_event_id) return error("FORBIDDEN", "外部事件尚未建立。", 403);
    state.sync.status = "proposed"; state.sync.direction = "pull"; state.sync.pending_change = { start_at: "2026-09-02T20:00:00+08:00", source: "external_calendar" }; state.sync.version += 1; state.syncConfirmation = null;
    return HttpResponse.json(state.sync);
  }),
  http.delete("/api/v1/external-calendar/syncs/external-sync-f5", async () => {
    if (!state.sync) return error("FORBIDDEN", "同步不存在。", 403);
    state.sync.status = "cancelled"; state.sync.version += 1; return HttpResponse.json(state.sync);
  }),

  http.post("/api/v1/organizations", async () => HttpResponse.json({ id: "organization-f5", name: "试点学习组织", owner_user_id: "demo-admin-f5", current_user_role: "owner", created_at: now }, { status: 201 })),
  http.post("/api/v1/organizations/organization-f5/members", async () => { state.org.learners = 2; return HttpResponse.json({ membership_id: "membership-f5", user_id: "demo-learner-f5", role: "learner" }, { status: 201 }); }),
  http.post("/api/v1/organizations/organization-f5/groups", async ({ request }) => { const body = z.object({ name: z.string() }).parse(await request.json()); state.org.groups = 2; return HttpResponse.json({ id: "group-f5", organization_id: "organization-f5", name: body.name, member_count: 0, created_at: now }, { status: 201 }); }),
  http.post("/api/v1/groups/group-f5/members", async () => HttpResponse.json({ membership_id: "group-membership-f5", user_id: "demo-learner-f5" }, { status: 201 })),
  http.post("/api/v1/groups/group-f5/course-assignments", async () => { state.org.assignments = 2; return HttpResponse.json({ assignment_id: "assignment-f5", course_id: COURSE_ID, due_at: null }, { status: 201 }); }),
  http.get("/api/v1/organizations/organization-f5/aggregate", async () => HttpResponse.json({ organization_id: "organization-f5", learner_count: state.org.learners, group_count: state.org.groups, assigned_course_count: state.org.assignments, completed_review_count: 5, attempted_question_count: 18, raw_learning_content_included: false })),
  http.get("/api/v1/organizations/organization-denied-f5/aggregate", async () => error("FORBIDDEN", "只有组织管理员能查看聚合数据。", 403)),

  http.post("/api/v1/cross-course-links", async ({ request }) => {
    const body = z.object({ source_course_id: z.string(), target_course_id: z.string(), selected_source_ref_ids: z.array(z.string()), purpose: z.string() }).parse(await request.json());
    state.cross = { id: "cross-link-f5", ...body, status: "active", version: 1, created_at: now, revoked_at: null };
    return HttpResponse.json(state.cross, { status: 201 });
  }),
  http.delete("/api/v1/cross-course-links/cross-link-f5", async ({ request }) => {
    if (!state.cross) return error("FORBIDDEN", "跨课关联不存在。", 403);
    if (Number(request.headers.get("If-Match")) !== state.cross.version) return error("VERSION_CONFLICT", "跨课程关系已经变化。", 409);
    state.cross.status = "revoked"; state.cross.version += 1; state.cross.revoked_at = now; return HttpResponse.json(state.cross);
  }),

  http.get("/api/v1/sft/projects/sft-project-f5/gate", async () => HttpResponse.json(sftProject())),
  http.post("/api/v1/sft/projects/sft-project-f5/launch", async () => {
    if (!gateReport().eligible_to_launch) return error("SFT_GATES_NOT_MET", "SFT 前置门尚未全部通过，已阻止创建训练任务。", 409);
    state.sft.launched = true; return HttpResponse.json(sftProject());
  }),
  http.post("/api/v1/sft/projects/sft-project-f5/consents", async () => { state.sft.consent = true; return HttpResponse.json({ consent_id: "consent-f5", status: "granted", source_ref_id: "source-f3-example" }, { status: 201 }); }),
  http.delete("/api/v1/sft/consents/consent-f5", async () => { state.sft.consent = false; state.sft.dataset = false; state.sft.launched = false; return HttpResponse.json({ consent_id: "consent-f5", status: "revoked" }); }),
  http.post("/api/v1/sft/projects/sft-project-f5/datasets", async () => { if (!state.sft.consent) return error("SFT_CONSENT_INVALID", "训练集包含未授权或已撤回的数据。", 409); state.sft.dataset = true; return HttpResponse.json({ dataset_snapshot_id: "dataset-f5", record_count: 1, content_hash: "a".repeat(64), status: "frozen" }, { status: 201 }); }),
  http.post("/api/v1/sft/projects/sft-project-f5/evaluations", async () => { if (!state.sft.dataset) return error("SFT_DATASET_INVALID", "训练数据快照不存在。", 409); state.sft.evaluation = true; return HttpResponse.json({ evaluation_id: "evaluation-f5", gate_report: gateReport() }, { status: 201 }); }),

  http.get("/api/v1/governance/metrics", async () => HttpResponse.json({ generated_at: now, workflow_runs: { completed: 28, failed: 2, running: 1 }, jobs: { completed: 43, failed: 3 }, guardrails: { TUTOR_ANSWER_LEAK: 4, CONFIRMATION_REQUIRED: 7 }, feedback: { open: 3, accepted: 9 }, external_adapters: { official_search: "disabled", external_calendar: "mock", notification: "mock", sft: "mock" }, performance: { p95_ms: 1380, failure_rate: 0.065 }, alerts: [{ code: "PROVIDER_DEGRADED", level: "warning", count: 2 }] })),
];
