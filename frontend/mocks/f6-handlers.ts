import { http, HttpResponse } from "msw";
import { z } from "zod";

import { resetF2MockState } from "./f2-handlers";
import { resetF3MockState } from "./f3-handlers";
import { resetF4MockState } from "./f4-handlers";
import { resetF5MockState } from "./f5-handlers";

export function resetF6MockState() {
  resetF2MockState();
  resetF3MockState();
  resetF4MockState();
  resetF5MockState();
}

export const f6Handlers = [
  http.get("/api/v1/capabilities", () => HttpResponse.json({
    api_contract_version: "2026-09-integration-v3",
    upload: {
      audio: { extensions: [".mp3", ".m4a", ".wav", ".webm", ".ogg", ".opus"], mime_types: ["audio/mpeg", "audio/mp4", "audio/wav", "audio/webm", "audio/ogg", "audio/opus"], max_bytes: 262144000, max_duration_seconds: 10800 },
      text: { extensions: [".txt", ".md", ".docx", ".pdf"], mime_types: ["text/plain", "text/markdown", "application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"], max_bytes: 52428800, max_duration_seconds: null },
      image: { extensions: [".jpg", ".jpeg", ".png", ".webp"], mime_types: ["image/jpeg", "image/png", "image/webp"], max_bytes: 20971520, max_duration_seconds: null },
      max_image_count_per_batch: 20,
      max_batch_items: 30,
      max_batch_bytes: 314572800,
      max_pdf_pages: 500,
      direct_upload_enabled: true,
      direct_upload_threshold_bytes: 8388608,
      direct_upload_expires_seconds: 900,
    },
    providers: {
      llm: { provider: "mock", configured: true }, asr: { provider: "mock", configured: true }, ocr: { provider: "mock", configured: true },
      official_search: { provider: "disabled", configured: false }, external_calendar: { provider: "disabled", configured: false },
      notification: { provider: "in_app", configured: true }, sft: { provider: "disabled", configured: false },
    },
    features: { p0_learning: true, p1_subjective_review: true, p1_external_calendar: false, p2_organizations: true, p2_cross_course: true, p2_sft: false, task_cancellation: true },
    security: { cookie_http_only: true, cookie_secure_in_production: true, same_site: "lax", csrf_origin_protection: true },
  })),
  http.get("/api/v1/me", () => HttpResponse.json({
    id: "demo-user-f6",
    status: "active",
    roles: ["learner", "internal_governance"],
    capabilities: ["learning:p0", "practice:subjective", "calendar:external", "organization:create", "organization:manage", "cross_course:manage", "sft:manage", "governance:read"],
  })),
  http.get("/api/v1/courses", () => HttpResponse.json([
    { id: "demo-course-f5", title_status: "confirmed", title: "受控能力验收课程", version: 1, material_counts: { usable: 2 }, created_at: "2026-09-01T09:00:00+08:00", updated_at: "2026-09-01T16:20:00+08:00" },
    { id: "demo-course-f2", title_status: "confirmed", title: "上传材料与内容确认", version: 2, material_counts: { usable: 3, needs_review: 1 }, created_at: "2026-08-30T09:00:00+08:00", updated_at: "2026-09-01T14:30:00+08:00" },
    { id: "demo-course-f3", title_status: "confirmed", title: "微积分 · 链式法则", version: 3, material_counts: { usable: 4 }, created_at: "2026-08-31T09:00:00+08:00", updated_at: "2026-09-01T14:30:00+08:00" },
    { id: "demo-course-f4", title_status: "confirmed", title: "复习计划与日历", version: 1, material_counts: { usable: 4 }, created_at: "2026-09-01T09:00:00+08:00", updated_at: "2026-09-01T14:30:00+08:00" },
  ])),
  http.get("/api/v1/organizations", () => HttpResponse.json([
    { id: "organization-f5", name: "试点学习组织", owner_user_id: "demo-admin-f5", current_user_role: "owner", created_at: "2026-09-01T16:20:00+08:00" },
  ])),
  http.get("/api/v1/sft/projects", () => HttpResponse.json([
    { id: "sft-project-f5", name: "Tutor 引导表达改进", use_case: "修复基线仍无法解决的引导表达问题", baseline_metric_name: "golden_set_pass_rate", baseline_score: 0.6, target_score: 0.85, status: "draft", provider_job_id: null, gate_report: {}, created_at: "2026-09-01T16:20:00+08:00", updated_at: "2026-09-01T16:20:00+08:00" },
  ])),
  http.get("/api/v1/cross-course-links", () => HttpResponse.json([])),
  http.get(/\/api\/v1\/courses\/([^/]+)\/learning-assets$/, ({ params }) => HttpResponse.json(String(params["0"]) === "demo-course-f3" ? [
    { id: "note-f3", course_id: "demo-course-f3", asset_type: "note", status: "ready", context_snapshot_id: "snapshot-note-f3", current_version_id: "note-version-f3-v1", version: 1, error_code: null, created_at: "2026-08-31T13:20:00+08:00", updated_at: "2026-08-31T13:20:00+08:00" },
    { id: "graph-f3", course_id: "demo-course-f3", asset_type: "graph", status: "ready", context_snapshot_id: "snapshot-graph-f3", current_version_id: "graph-version-f3-v1", version: 1, error_code: null, created_at: "2026-08-31T13:20:00+08:00", updated_at: "2026-08-31T13:20:00+08:00" },
  ] : [])),
  http.get("/api/v1/courses/demo-course-f3/materials", () => HttpResponse.json({ items: [
    { id: "material-f3-notes", course_id: "demo-course-f3", batch_id: "batch-f3", declared_type: "text", detected_type: "text", display_name: "微积分课堂整理.txt", detected_mime: "text/plain", byte_size: 4210, status: "usable", active_parse_version_id: "material-version-f3-v1", error_code: null, error_message: null, retryable: false, version: 1, created_at: "2026-08-31T13:20:00+08:00", updated_at: "2026-08-31T13:20:00+08:00", jobs: [] },
  ], next_cursor: null })),
  http.post("/api/v1/courses/demo-course-f3/context-snapshots", async ({ request }) => {
    const body = z.object({ task_type: z.string(), selected_materials: z.array(z.object({ id: z.string(), parse_version: z.string(), selected_order: z.number() })) }).parse(await request.json());
    return HttpResponse.json({ id: `snapshot-${body.task_type}-f3`, course_id: "demo-course-f3", task_type: body.task_type, context_mode: "indexed_full", status: "ready", coverage_status: "complete", token_estimate: 860, segment_count: 3, policy_version: "indexed-context-v2", segment_plan: [], index_status: "ready", indexed_chunk_count: 3, embedding_provider: "local", embedding_model_id: "local-hash-ngram-v1", retrieval_config_version: "hybrid-embedding-v2", materials: body.selected_materials.map((item) => ({ material_id: item.id, parse_version_id: item.parse_version, selected_order: item.selected_order, display_name: "微积分课堂整理.txt", covered_locator_range: {} })), source_ref_ids: ["source-f3-chain", "source-f3-example"], created_at: "2026-09-01T14:30:00+08:00" }, { status: 201 });
  }),
  http.get(/\/api\/v1\/courses\/([^/]+)\/quizzes$/, ({ params }) => HttpResponse.json(String(params["0"]) === "demo-course-f3" ? [
    { id: "quiz-f3", course_id: "demo-course-f3", context_snapshot_id: "snapshot-quiz-f3", status: "ready", difficulty: "medium", requested_count: 2, published_count: 1, created_at: "2026-08-31T13:20:00+08:00", updated_at: "2026-08-31T13:20:00+08:00" },
  ] : [])),
  http.get(/\/api\/v1\/courses\/([^/]+)\/tutor-sessions$/, ({ params }) => HttpResponse.json(String(params["0"]) === "demo-course-f3" ? [
    { id: "tutor-rag-f3", course_id: "demo-course-f3", context_snapshot_id: "snapshot-tutor-rag-f3", context_mode: "tutor_rag", learning_goal: "真正理解链式法则，不靠背答案", status: "active", fsm_state: "diagnose", turn_count: 0, max_turns: 8, version: 1, created_at: "2026-08-31T13:20:00+08:00", updated_at: "2026-08-31T13:20:00+08:00" },
    { id: "tutor-direct-f3", course_id: "demo-course-f3", context_snapshot_id: "snapshot-tutor-direct-f3", context_mode: "direct_full", learning_goal: "用完整短材料理解链式法则", status: "active", fsm_state: "diagnose", turn_count: 0, max_turns: 8, version: 1, created_at: "2026-08-31T13:20:00+08:00", updated_at: "2026-08-31T13:20:00+08:00" },
  ] : [])),
  http.get(/\/api\/v1\/courses\/([^/]+)\/review-plans$/, ({ params }) => HttpResponse.json(String(params["0"]) === "demo-course-f4" ? [
    { id: "plan-f4", course_id: "demo-course-f4", status: "ready", version: 1, next_action: { type: "note_review", target_id: "note-f3" }, requires_confirmation: true, created_at: "2026-09-01T14:30:00+08:00", updated_at: "2026-09-01T14:30:00+08:00" },
  ] : [])),
  http.get(/\/api\/v1\/courses\/([^/]+)\/workflow-runs$/, ({ params }) => HttpResponse.json(String(params["0"]) === "demo-course-f4" ? [
    { id: "run-plan-f4", course_id: "demo-course-f4", task_type: "generate_review_plan", status: "succeeded", started_at: "2026-09-01T14:30:00+08:00", finished_at: "2026-09-01T14:30:02+08:00" },
  ] : [])),
  http.get(/\/api\/v1\/tasks\/([^/]+)$/, ({ params }) => HttpResponse.json({ task_id: String(params["0"]), run_id: "run-mock-f6", job_type: "tutor_turn", target_id: "turn-f3", status: "queued", cancellable: true, error_code: null, created_at: "2026-09-01T14:30:00+08:00", started_at: null, finished_at: null })),
  http.delete(/\/api\/v1\/tasks\/([^/]+)$/, ({ params }) => HttpResponse.json({ task_id: String(params["0"]), run_id: "run-mock-f6", job_type: "tutor_turn", target_id: "turn-f3", status: "cancelled", cancellable: false, error_code: "TASK_CANCELLED_BY_USER", created_at: "2026-09-01T14:30:00+08:00", started_at: null, finished_at: "2026-09-01T14:31:00+08:00" })),
  http.post("/api/v1/auth/invite-session", async ({ request }) => {
    const body = z.object({ invite_code: z.string() }).safeParse(await request.clone().json());
    if (!body.success || body.data.invite_code !== "F6-DEMO-2026") return;
    resetF6MockState();
    return HttpResponse.json({
      user: { id: "demo-user-f6", status: "active", roles: ["learner", "internal_governance"], capabilities: ["learning:p0", "practice:subjective", "calendar:external", "organization:create", "organization:manage", "cross_course:manage", "sft:manage", "governance:read"] },
      expires_at: "2026-09-01T23:59:59+08:00",
    });
  }),
];
