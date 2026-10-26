import { delay, http, HttpResponse } from "msw";
import { z } from "zod";

import type {
  Batch,
  ContextSnapshot,
  Course,
  Material,
  MaterialVersion,
  Segment,
  SourceRef,
  TitleCandidateResponse,
} from "@/lib/api/types";

const COURSE_ID = "demo-course-f2";
const now = () => new Date().toISOString();

const manifestSchema = z.object({
  items: z.array(z.object({
    client_item_id: z.string(),
    declared_type: z.enum(["audio", "text", "board_image", "handwriting_image"]),
    upload_index: z.number().int().optional(),
    text: z.string().optional(),
    display_name: z.string(),
  })).min(1),
});

type ManifestItem = z.infer<typeof manifestSchema>["items"][number];

type F2MockState = {
  authenticated: boolean;
  course: Course;
  materials: Map<string, Material>;
  versions: Map<string, MaterialVersion>;
  batches: Map<string, Batch>;
  snapshots: Map<string, ContextSnapshot>;
  sequence: number;
};

function createState(): F2MockState {
  const created = now();
  return {
    authenticated: false,
    course: {
      id: COURSE_ID,
      title_status: "unnamed",
      title: null,
      version: 1,
      created_at: created,
      updated_at: created,
      material_counts: {},
    },
    materials: new Map(),
    versions: new Map(),
    batches: new Map(),
    snapshots: new Map(),
    sequence: 0,
  };
}

let state = createState();

export function resetF2MockState() {
  state = createState();
}

function nextId(prefix: string) {
  state.sequence += 1;
  return `${prefix}-${state.sequence}`;
}

function error(code: string, message: string, status = 400) {
  return HttpResponse.json({ error: { code, message, request_id: `mock-${code.toLowerCase()}` } }, { status });
}

function countMaterials() {
  return Array.from(state.materials.values()).reduce<Record<string, number>>((counts, material) => {
    counts[material.status] = (counts[material.status] ?? 0) + 1;
    return counts;
  }, {});
}

function courseDetail() {
  return { ...state.course, material_counts: countMaterials() };
}

function locatorFor(type: Material["declared_type"], index: number) {
  if (type === "audio") return { locator_type: "time_range", start_ms: index * 42_000, end_ms: index * 42_000 + 38_000, page_no: null, bbox: null, paragraph_no: null };
  if (type === "board_image" || type === "handwriting_image") return { locator_type: "image_bbox", start_ms: null, end_ms: null, page_no: 1, bbox: [0.12, 0.18, 0.86, 0.42], paragraph_no: null };
  return { locator_type: "paragraph", start_ms: null, end_ms: null, page_no: null, bbox: null, paragraph_no: index + 1 };
}

function buildVersion(material: Material, text?: string): MaterialVersion {
  const needsReview = material.status === "needs_review";
  const versionId = material.active_parse_version_id ?? `parse-${material.id}-v1`;
  const segmentTexts = text
    ? [text]
    : material.declared_type === "audio"
      ? ["导数描述函数在某一点附近的瞬时变化率。", "复合函数求导时需要按照链式法则逐层计算。"]
      : material.declared_type === "handwriting_image"
        ? ["极限描述自变量趋近时函数值的变化趋势。", "连续要求函数值与该点极限相等。"]
        : ["课堂材料强调：先理解概念之间的关系，再用练习检验。"];
  const segments: Segment[] = segmentTexts.map((segmentText, index) => ({
    id: `source-${material.id}-${index + 1}`,
    ordinal: index + 1,
    text: segmentText,
    ...locatorFor(material.declared_type, index),
    confidence: needsReview && index === 0 ? 0.58 : 0.94,
    review_required: needsReview && index === 0,
    review_accepted: false,
  }));
  return {
    id: versionId,
    material_id: material.id,
    version_no: 1,
    source_kind: "provider_parse",
    parse_status: needsReview ? "needs_review" : "ready",
    parser: material.declared_type === "audio" ? "volc-asr" : "volc-ocr-text",
    provider: "volcengine",
    model_id: "contract-mock-f2",
    confidence_summary: { min: Math.min(...segments.map((item) => item.confidence ?? 1)) },
    created_by: "workflow",
    created_at: now(),
    segments,
  };
}

function materialFromManifest(item: ManifestItem, file: FormDataEntryValue | undefined, batchId: string): Material {
  const id = nextId("material");
  const failed = item.display_name.includes("失败");
  const status = failed ? "failed" : item.declared_type === "handwriting_image" ? "needs_review" : "usable";
  const versionId = failed ? null : `parse-${id}-v1`;
  const created = now();
  const material: Material = {
    id,
    course_id: COURSE_ID,
    batch_id: batchId,
    declared_type: item.declared_type,
    detected_type: item.declared_type,
    display_name: item.display_name,
    detected_mime: file instanceof File ? file.type || null : item.declared_type === "text" ? "text/plain" : null,
    byte_size: file instanceof File ? file.size : new TextEncoder().encode(item.text ?? "").length,
    status,
    active_parse_version_id: versionId,
    error_code: failed ? "PROVIDER_TEMPORARY" : null,
    error_message: failed ? "本次识别服务暂时不可用，可以重试或删除这份材料。" : null,
    retryable: failed,
    version: 1,
    created_at: created,
    updated_at: created,
    jobs: [{ id: nextId("job"), status: failed ? "failed" : "succeeded", job_type: "extract", attempt: 1, max_attempts: 3, error_code: failed ? "PROVIDER_TEMPORARY" : null }],
  };
  if (versionId) state.versions.set(versionId, buildVersion(material, item.text));
  return material;
}

function titleCandidate(): TitleCandidateResponse | null {
  const sourceIds = Array.from(state.materials.values())
    .filter((item) => item.status === "usable" && item.active_parse_version_id)
    .flatMap((item) => state.versions.get(item.active_parse_version_id ?? "")?.segments.slice(0, 1).map((segment) => segment.id) ?? []);
  if (!sourceIds.length) return null;
  return {
    id: "title-candidate-f2",
    course_id: COURSE_ID,
    status: "ready",
    candidates: [
      { id: "candidate-calculus", title: "微积分 · 导数与极限", source_ref_ids: sourceIds.slice(0, 2), confidence: 0.93 },
      { id: "candidate-functions", title: "函数变化率与连续性", source_ref_ids: sourceIds.slice(0, 2), confidence: 0.82 },
    ],
    source_ref_ids: sourceIds,
    prompt_version: "title-v1",
    requested_model_id: "deepseek-chat",
    returned_model_id: "contract-mock-f2",
    created_at: now(),
  };
}

function findSource(sourceId: string): { material: Material; version: MaterialVersion; segment: Segment } | null {
  for (const version of state.versions.values()) {
    const segment = version.segments.find((item) => item.id === sourceId);
    if (!segment) continue;
    const material = state.materials.get(version.material_id);
    if (material) return { material, version, segment };
  }
  return null;
}

export const f2Handlers = [
  http.post("/api/v1/auth/invite-session", async ({ request }) => {
    await delay(120);
    const body = z.object({ invite_code: z.string() }).parse(await request.json());
    if (body.invite_code !== "F2-DEMO-2026") return error("INVITE_INVALID", "邀请码不正确，请检查后再试。", 401);
    resetF2MockState();
    state.authenticated = true;
    return HttpResponse.json({ user: { id: "demo-user", status: "active" }, expires_at: now() });
  }),

  http.get("/api/v1/me", () => HttpResponse.json({ id: "demo-user", status: "active" })),

  http.post("/api/v1/courses", async () => {
    await delay(100);
    return HttpResponse.json(state.course, { status: 201 });
  }),

  http.get("/api/v1/courses/:courseId", async ({ params }) => {
    await delay(80);
    if (params.courseId !== COURSE_ID) return error("NOT_FOUND", "课程不存在。", 404);
    return HttpResponse.json(courseDetail());
  }),

  http.get("/api/v1/courses/:courseId/materials", async ({ params, request }) => {
    await delay(90);
    if (params.courseId !== COURSE_ID) return error("NOT_FOUND", "课程不存在。", 404);
    const status = new URL(request.url).searchParams.get("status");
    const items = Array.from(state.materials.values()).filter((item) => !status || item.status === status);
    return HttpResponse.json({ items, next_cursor: null });
  }),

  http.post("/api/v1/courses/:courseId/material-batches", async ({ params, request }) => {
    await delay(260);
    if (params.courseId !== COURSE_ID) return error("NOT_FOUND", "课程不存在。", 404);
    const form = await request.formData();
    const rawManifest = form.get("manifest");
    if (typeof rawManifest !== "string") return error("INVALID_UPLOAD_MANIFEST", "上传清单格式无效。");
    const parsed = manifestSchema.safeParse(JSON.parse(rawManifest));
    if (!parsed.success) return error("INVALID_UPLOAD_MANIFEST", "上传清单格式无效。");
    const files = form.getAll("files");
    const batchId = nextId("batch");
    const materials = parsed.data.items.map((item) => materialFromManifest(item, item.upload_index === undefined ? undefined : files[item.upload_index], batchId));
    materials.forEach((material) => state.materials.set(material.id, material));
    const failedCount = materials.filter((item) => item.status === "failed").length;
    const batch: Batch = {
      id: batchId,
      course_id: COURSE_ID,
      status: failedCount === materials.length ? "failed" : "completed",
      item_count: materials.length,
      success_count: materials.length - failedCount,
      failed_count: failedCount,
      created_at: now(),
      updated_at: now(),
      materials,
    };
    state.batches.set(batch.id, batch);
    state.course = { ...state.course, version: state.course.version + 1, updated_at: now() };
    return HttpResponse.json(batch, { status: 202 });
  }),

  http.get("/api/v1/material-batches/:batchId", ({ params }) => {
    const batch = state.batches.get(String(params.batchId));
    return batch ? HttpResponse.json(batch) : error("NOT_FOUND", "上传批次不存在。", 404);
  }),

  http.get("/api/v1/courses/:courseId/title-candidate", async ({ params }) => {
    await delay(70);
    if (params.courseId !== COURSE_ID) return error("NOT_FOUND", "课程不存在。", 404);
    const candidate = titleCandidate();
    return candidate ? HttpResponse.json(candidate) : error("TITLE_SCOPE_EMPTY", "当前还没有课程名称候选。", 404);
  }),

  http.post(/\/api\/v1\/courses\/[^/]+\/title-candidate:regenerate$/, async () => {
    await delay(120);
    return HttpResponse.json({ task_id: "title-task-f2", status: "succeeded" });
  }),

  http.post("/api/v1/courses/:courseId/title-confirmations", async ({ params, request }) => {
    await delay(100);
    if (params.courseId !== COURSE_ID) return error("NOT_FOUND", "课程不存在。", 404);
    const body = z.object({ candidate_id: z.string().nullable(), edited_title: z.string().nullable(), expected_course_version: z.number() }).parse(await request.json());
    const candidate = titleCandidate()?.candidates.find((item) => item.id === body.candidate_id);
    const selectedTitle = body.edited_title || candidate?.title;
    if (!selectedTitle) return error("INVALID_INPUT", "请选择或填写课程名称。");
    state.course = { ...state.course, title: selectedTitle, title_status: "confirmed", version: state.course.version + 1, updated_at: now() };
    return HttpResponse.json(state.course);
  }),

  http.get("/api/v1/materials/:materialId", async ({ params }) => {
    await delay(70);
    const material = state.materials.get(String(params.materialId));
    return material ? HttpResponse.json(material) : error("NOT_FOUND", "材料不存在。", 404);
  }),

  http.get("/api/v1/materials/:materialId/versions/:versionId", async ({ params }) => {
    await delay(80);
    const version = state.versions.get(String(params.versionId));
    return version && version.material_id === params.materialId ? HttpResponse.json(version) : error("SOURCE_REF_INVALID", "解析版本不存在。", 404);
  }),

  http.patch("/api/v1/materials/:materialId/corrections", async ({ params, request }) => {
    await delay(140);
    const material = state.materials.get(String(params.materialId));
    if (!material?.active_parse_version_id) return error("NOT_FOUND", "材料不存在。", 404);
    const current = state.versions.get(material.active_parse_version_id);
    if (!current) return error("SOURCE_REF_INVALID", "解析版本不存在。", 404);
    const body = z.object({ corrections: z.array(z.object({ segment_id: z.string(), action: z.enum(["replace", "accept"]), text: z.string().nullable() })) }).parse(await request.json());
    const nextIdValue = `parse-${material.id}-v${current.version_no + 1}`;
    const nextVersion: MaterialVersion = {
      ...current,
      id: nextIdValue,
      version_no: current.version_no + 1,
      source_kind: "user_correction",
      parse_status: "ready",
      created_by: "user",
      created_at: now(),
      segments: current.segments.map((segment) => {
        const correction = body.corrections.find((item) => item.segment_id === segment.id);
        return correction ? { ...segment, text: correction.action === "replace" ? correction.text ?? segment.text : segment.text, review_required: false, review_accepted: true, confidence: 1 } : segment;
      }),
    };
    state.versions.set(nextVersion.id, nextVersion);
    state.materials.set(material.id, { ...material, status: "usable", active_parse_version_id: nextVersion.id, version: material.version + 1, updated_at: now() });
    return HttpResponse.json(nextVersion);
  }),

  http.post("/api/v1/materials/:materialId/retry", async ({ params }) => {
    await delay(130);
    const material = state.materials.get(String(params.materialId));
    if (!material) return error("NOT_FOUND", "材料不存在。", 404);
    const repaired = { ...material, status: "usable", retryable: false, error_code: null, error_message: null, version: material.version + 1, active_parse_version_id: `parse-${material.id}-v1`, updated_at: now() };
    state.materials.set(material.id, repaired);
    state.versions.set(repaired.active_parse_version_id, buildVersion(repaired));
    return HttpResponse.json({ task_id: nextId("retry-task"), status: "succeeded" }, { status: 202 });
  }),

  http.post("/api/v1/materials/:materialId/deletion-preview", async ({ params }) => {
    await delay(80);
    const material = state.materials.get(String(params.materialId));
    if (!material) return error("NOT_FOUND", "材料不存在。", 404);
    return HttpResponse.json({
      confirmation_id: `confirmation-${material.id}-0123456789`,
      expires_at: now(),
      impact: { material: material.display_name, parse_versions: material.active_parse_version_id ? 1 : 0, source_refs: material.active_parse_version_id ? state.versions.get(material.active_parse_version_id)?.segments.length ?? 0 : 0, context_snapshots_may_become_stale: state.snapshots.size },
    });
  }),

  http.delete("/api/v1/materials/:materialId", async ({ params }) => {
    await delay(100);
    const materialId = String(params.materialId);
    if (!state.materials.has(materialId)) return error("NOT_FOUND", "材料不存在。", 404);
    state.materials.delete(materialId);
    return HttpResponse.json({ material_id: materialId, status: "deleting", task_id: nextId("delete-task") }, { status: 202 });
  }),

  http.post("/api/v1/courses/:courseId/context-snapshots", async ({ params, request }) => {
    await delay(150);
    if (params.courseId !== COURSE_ID) return error("NOT_FOUND", "课程不存在。", 404);
    const body = z.object({ task_type: z.string(), selected_materials: z.array(z.object({ id: z.string(), parse_version: z.string(), selected_order: z.number() })).min(1) }).parse(await request.json());
    const selected = body.selected_materials
      .sort((a, b) => a.selected_order - b.selected_order)
      .map((item) => ({ material: state.materials.get(item.id), version: state.versions.get(item.parse_version), selected_order: item.selected_order }))
      .filter((item): item is { material: Material; version: MaterialVersion; selected_order: number } => Boolean(item.material && item.version));
    if (!selected.length) return error("CONTEXT_EMPTY", "至少选择一份可用材料。");
    const snapshotId = nextId("snapshot");
    const sourceIds = selected.flatMap((item) => item.version.segments.map((segment) => segment.id));
    const snapshot: ContextSnapshot = {
      id: snapshotId,
      course_id: COURSE_ID,
      task_type: body.task_type,
      context_mode: "indexed_full",
      status: "ready",
      coverage_status: "complete",
      token_estimate: sourceIds.length * 128,
      segment_count: sourceIds.length,
      policy_version: "context-v1",
      segment_plan: [],
      index_status: "ready",
      indexed_chunk_count: sourceIds.length,
      embedding_provider: "local",
      embedding_model_id: "local-hash-ngram-v1",
      retrieval_config_version: "hybrid-embedding-v2",
      materials: selected.map((item) => ({ material_id: item.material.id, parse_version_id: item.version.id, selected_order: item.selected_order, display_name: item.material.display_name, covered_locator_range: { complete: true } })),
      source_ref_ids: sourceIds,
      created_at: now(),
    };
    state.snapshots.set(snapshot.id, snapshot);
    return HttpResponse.json(snapshot, { status: 201 });
  }),

  http.get("/api/v1/context-snapshots/:snapshotId", async ({ params }) => {
    await delay(80);
    const snapshot = state.snapshots.get(String(params.snapshotId));
    return snapshot ? HttpResponse.json(snapshot) : error("NOT_FOUND", "上下文快照不存在。", 404);
  }),

  http.get("/api/v1/source-refs/:sourceId", async ({ params }) => {
    await delay(70);
    const found = findSource(String(params.sourceId));
    if (!found) return error("SOURCE_REF_INVALID", "来源位置不存在或已失效。", 404);
    const { material, version, segment } = found;
    const source: SourceRef = {
      id: segment.id,
      material_id: material.id,
      material_version_id: version.id,
      display_name: material.display_name,
      material_type: material.declared_type,
      text: segment.text,
      locator_type: segment.locator_type,
      start_ms: segment.start_ms,
      end_ms: segment.end_ms,
      page_no: segment.page_no,
      bbox: segment.bbox,
      paragraph_no: segment.paragraph_no,
      confidence: segment.confidence,
      preview_path: `/api/v1/materials/${material.id}/original`,
    };
    return HttpResponse.json(source);
  }),

  http.get("/api/v1/materials/:materialId/original", ({ params }) => {
    const material = state.materials.get(String(params.materialId));
    if (!material) return error("NOT_FOUND", "材料原件不存在。", 404);
    if (material.declared_type === "board_image" || material.declared_type === "handwriting_image") {
      const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="760"><rect width="100%" height="100%" fill="#eee8da"/><path d="M110 180h860M160 290h760M130 410h900M210 535h650" stroke="#29463d" stroke-width="11" stroke-linecap="round" opacity=".72"/><text x="110" y="110" font-family="serif" font-size="42" fill="#7e4c2a">课堂手写原件 · 合同 Mock</text></svg>`;
      return new HttpResponse(svg, { headers: { "Content-Type": "image/svg+xml" } });
    }
    return new HttpResponse(material.declared_type === "audio" ? new Uint8Array() : "课堂文本原件（合同 Mock）", { headers: { "Content-Type": material.declared_type === "audio" ? "audio/mp4" : "text/plain; charset=utf-8" } });
  }),
];
