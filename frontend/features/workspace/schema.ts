import { z } from "zod";

export const workspaceActionTypeSchema = z.enum([
  "upload_material",
  "generate_note",
  "generate_quiz",
  "generate_review_plan",
  "tutor",
  "quiz",
  "wrong_retry",
  "note_review",
]);

export const workspaceResponseSchema = z.object({
  course_id: z.string(),
  action: z.object({
    type: workspaceActionTypeSchema,
    target_id: z.string(),
    reason: z.string(),
    duration_min: z.number().int().nonnegative(),
    plan_id: z.string().nullable().optional(),
  }),
  derived_by: z.enum(["workflow", "model", "fallback_rule"]),
});

export const courseDetailSchema = z.object({
  id: z.string(),
  title_status: z.string(),
  title: z.string().nullable(),
  version: z.number().int(),
  created_at: z.string(),
  updated_at: z.string(),
  material_counts: z.record(z.string(), z.number().int()),
});

export const materialSummarySchema = z.object({
  id: z.string(),
  course_id: z.string(),
  batch_id: z.string(),
  declared_type: z.string(),
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
  jobs: z.array(z.unknown()).optional().default([]),
});

export const materialListSchema = z.object({
  items: z.array(materialSummarySchema),
  next_cursor: z.string().nullable().optional(),
});

export type WorkspaceResponse = z.infer<typeof workspaceResponseSchema>;
export type CourseDetail = z.infer<typeof courseDetailSchema>;
export type MaterialSummary = z.infer<typeof materialSummarySchema>;

export type WorkspaceView = {
  course: CourseDetail;
  workspace: WorkspaceResponse;
  materials: MaterialSummary[];
};
