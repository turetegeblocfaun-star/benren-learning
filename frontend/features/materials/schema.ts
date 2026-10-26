import { z } from "zod";

export const userSchema = z.object({
  id: z.string(),
  status: z.string(),
  roles: z.array(z.string()).default([]),
  capabilities: z.array(z.string()).default([]),
});
export const sessionSchema = z.object({ user: userSchema, expires_at: z.string() });

export const courseSchema = z.object({
  id: z.string(),
  title_status: z.string(),
  title: z.string().nullable(),
  version: z.number().int(),
  created_at: z.string(),
  updated_at: z.string(),
  material_counts: z.record(z.string(), z.number().int()).optional(),
});

const jobSchema = z.object({
  id: z.string(),
  status: z.string(),
  job_type: z.string(),
  attempt: z.number().int(),
  max_attempts: z.number().int(),
  error_code: z.string().nullable(),
});

export const materialSchema = z.object({
  id: z.string(),
  course_id: z.string(),
  batch_id: z.string(),
  declared_type: z.enum(["audio", "text", "board_image", "handwriting_image"]),
  detected_type: z.string().nullable(),
  display_name: z.string(),
  detected_mime: z.string().nullable(),
  byte_size: z.number().int().nonnegative(),
  status: z.string(),
  active_parse_version_id: z.string().nullable(),
  error_code: z.string().nullable(),
  error_message: z.string().nullable(),
  retryable: z.boolean(),
  version: z.number().int(),
  created_at: z.string(),
  updated_at: z.string(),
  jobs: z.array(jobSchema),
});

export const materialListSchema = z.object({ items: z.array(materialSchema), next_cursor: z.string().nullable().optional() });

export const batchSchema = z.object({
  id: z.string(),
  course_id: z.string(),
  status: z.string(),
  item_count: z.number().int(),
  success_count: z.number().int(),
  failed_count: z.number().int(),
  created_at: z.string(),
  updated_at: z.string(),
  materials: z.array(materialSchema),
});

export const directUploadPrepareSchema = z.object({
  items: z.array(z.object({
    client_item_id: z.string(),
    upload_url: z.string().url(),
    upload_token: z.string(),
    expires_at: z.string(),
  })),
});

export const segmentSchema = z.object({
  id: z.string(),
  ordinal: z.number().int(),
  text: z.string(),
  locator_type: z.string(),
  start_ms: z.number().int().nullable(),
  end_ms: z.number().int().nullable(),
  page_no: z.number().int().nullable(),
  bbox: z.array(z.number()).nullable(),
  paragraph_no: z.number().int().nullable(),
  confidence: z.number().nullable(),
  review_required: z.boolean(),
  review_accepted: z.boolean(),
});

export const materialVersionSchema = z.object({
  id: z.string(),
  material_id: z.string(),
  version_no: z.number().int(),
  source_kind: z.string(),
  parse_status: z.string(),
  parser: z.string().nullable(),
  provider: z.string().nullable(),
  model_id: z.string().nullable(),
  confidence_summary: z.record(z.string(), z.unknown()),
  created_by: z.string(),
  created_at: z.string(),
  segments: z.array(segmentSchema),
});

export const titleCandidateSchema = z.object({
  id: z.string(),
  course_id: z.string(),
  status: z.string(),
  candidates: z.array(z.object({ id: z.string(), title: z.string(), source_ref_ids: z.array(z.string()), confidence: z.number() })),
  source_ref_ids: z.array(z.string()),
  prompt_version: z.string(),
  requested_model_id: z.string(),
  returned_model_id: z.string().nullable(),
  created_at: z.string(),
});

export const contextSnapshotSchema = z.object({
  id: z.string(),
  course_id: z.string(),
  task_type: z.string(),
  context_mode: z.string(),
  status: z.string(),
  coverage_status: z.string(),
  token_estimate: z.number().int(),
  segment_count: z.number().int(),
  policy_version: z.string(),
  segment_plan: z.array(z.record(z.string(), z.unknown())),
  index_status: z.string().default("legacy"),
  indexed_chunk_count: z.number().int().nonnegative().default(0),
  embedding_provider: z.string().default("legacy"),
  embedding_model_id: z.string().default("legacy"),
  retrieval_config_version: z.string().default("legacy"),
  materials: z.array(z.object({ material_id: z.string(), parse_version_id: z.string(), selected_order: z.number().int(), display_name: z.string(), covered_locator_range: z.record(z.string(), z.unknown()) })),
  source_ref_ids: z.array(z.string()),
  created_at: z.string(),
});

export const sourceRefSchema = z.object({
  id: z.string(),
  material_id: z.string(),
  material_version_id: z.string(),
  display_name: z.string(),
  material_type: z.string(),
  text: z.string(),
  locator_type: z.string(),
  start_ms: z.number().int().nullable(),
  end_ms: z.number().int().nullable(),
  page_no: z.number().int().nullable(),
  bbox: z.array(z.number()).nullable(),
  paragraph_no: z.number().int().nullable(),
  confidence: z.number().nullable(),
  preview_path: z.string(),
});

export const taskRefSchema = z.object({ task_id: z.string(), status: z.string() });
export const taskStatusSchema = z.object({
  task_id: z.string(),
  run_id: z.string(),
  job_type: z.string(),
  target_id: z.string(),
  status: z.string(),
  cancellable: z.boolean(),
  error_code: z.string().nullable(),
  created_at: z.string(),
  started_at: z.string().nullable(),
  finished_at: z.string().nullable(),
});
export const deletePreviewSchema = z.object({ confirmation_id: z.string(), expires_at: z.string(), impact: z.record(z.string(), z.unknown()) });
export const deleteResponseSchema = z.object({ material_id: z.string(), status: z.string(), task_id: z.string() });
