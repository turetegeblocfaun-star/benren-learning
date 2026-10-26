import { z } from "zod";

const uploadTypeCapabilitySchema = z.object({
  extensions: z.array(z.string()),
  mime_types: z.array(z.string()),
  max_bytes: z.number().int().positive(),
  max_duration_seconds: z.number().int().positive().nullable(),
});

export const capabilitiesSchema = z.object({
  api_contract_version: z.string(),
  upload: z.object({
    audio: uploadTypeCapabilitySchema,
    text: uploadTypeCapabilitySchema,
    image: uploadTypeCapabilitySchema,
    max_image_count_per_batch: z.number().int().positive(),
    max_batch_items: z.number().int().positive(),
    max_batch_bytes: z.number().int().positive(),
    max_pdf_pages: z.number().int().positive(),
    direct_upload_enabled: z.boolean(),
    direct_upload_threshold_bytes: z.number().int().positive(),
    direct_upload_expires_seconds: z.number().int().positive(),
  }),
  providers: z.record(z.string(), z.object({ provider: z.string(), configured: z.boolean() })),
  features: z.record(z.string(), z.boolean()),
  security: z.object({
    cookie_http_only: z.boolean(),
    cookie_secure_in_production: z.boolean(),
    same_site: z.string(),
    csrf_origin_protection: z.boolean(),
  }),
});

export type SystemCapabilities = z.infer<typeof capabilitiesSchema>;

export const healthSchema = z.object({
  status: z.literal("ok"),
  api: z.literal("ok"),
  database: z.literal("ok"),
  worker: z.enum(["ok", "not_running"]),
  stage: z.number().int(),
});

export const courseListSchema = z.array(z.object({
  id: z.string(),
  title_status: z.string(),
  title: z.string().nullable(),
  version: z.number().int(),
  material_counts: z.record(z.string(), z.number().int()),
  created_at: z.string(),
  updated_at: z.string(),
}));

export const learningAssetListSchema = z.array(z.object({
  id: z.string(),
  course_id: z.string(),
  asset_type: z.string(),
  status: z.string(),
  context_snapshot_id: z.string(),
  current_version_id: z.string().nullable(),
  version: z.number().int(),
  error_code: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
}));

export const tutorSessionListSchema = z.array(z.object({
  id: z.string(),
  course_id: z.string(),
  context_snapshot_id: z.string(),
  context_mode: z.string(),
  learning_goal: z.string(),
  status: z.string(),
  fsm_state: z.string(),
  turn_count: z.number().int(),
  max_turns: z.number().int(),
  version: z.number().int(),
  created_at: z.string(),
  updated_at: z.string(),
}));

export const quizListSchema = z.array(z.object({
  id: z.string(),
  course_id: z.string(),
  context_snapshot_id: z.string(),
  status: z.string(),
  difficulty: z.string(),
  requested_count: z.number().int(),
  published_count: z.number().int(),
  created_at: z.string(),
  updated_at: z.string(),
}));

export const reviewPlanListSchema = z.array(z.object({
  id: z.string(),
  course_id: z.string(),
  status: z.string(),
  version: z.number().int(),
  next_action: z.record(z.string(), z.unknown()),
  requires_confirmation: z.boolean(),
  created_at: z.string(),
  updated_at: z.string(),
}));

export const workflowRunListSchema = z.array(z.object({
  id: z.string(),
  course_id: z.string().nullable(),
  task_type: z.string(),
  status: z.string(),
  started_at: z.string(),
  finished_at: z.string().nullable(),
}));
