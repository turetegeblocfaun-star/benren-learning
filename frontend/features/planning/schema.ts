import { z } from "zod";

const isoDate = z.string();

export const nextActionSchema = z.object({
  type: z.string(),
  target_id: z.string(),
  reason: z.string(),
  duration_min: z.number().int(),
  plan_id: z.string().nullable().optional(),
});

export const planningWorkspaceSchema = z.object({
  course_id: z.string(),
  action: nextActionSchema,
  derived_by: z.enum(["workflow", "model", "fallback_rule"]),
});

export const calendarCandidateSchema = z.object({
  id: z.string(),
  ordinal: z.number().int(),
  start_at: isoDate,
  end_at: isoDate,
  timezone: z.string(),
  reason: z.string(),
  confidence: z.union([z.number(), z.enum(["high", "medium", "low"])]),
  status: z.string(),
  source_kind: z.string(),
  version: z.number().int(),
  created_at: isoDate,
  updated_at: isoDate,
});

export const reviewPlanSchema = z.object({
  id: z.string(),
  course_id: z.string(),
  status: z.string(),
  version: z.number().int(),
  next_action: nextActionSchema.nullable(),
  calendar_candidates: z.array(calendarCandidateSchema),
  assumptions: z.array(z.string()),
  conflicts: z.array(z.string()),
  requires_confirmation: z.boolean(),
  prompt_version: z.string(),
  requested_model_id: z.string(),
  returned_model_id: z.string().nullable(),
  fallback_reason: z.string().nullable(),
  error_code: z.string().nullable(),
  error_message: z.string().nullable(),
  created_at: isoDate,
  updated_at: isoDate,
});

export const reviewPlanTaskSchema = z.object({
  plan: reviewPlanSchema,
  task_id: z.string(),
});

export const actionEventSchema = z.object({
  id: z.string(),
  plan_id: z.string(),
  event_type: z.enum(["started", "skipped", "completed"]),
  reason: z.string().nullable(),
  created_at: isoDate,
});

export const confirmationPreviewSchema = z.object({
  confirmation_id: z.string(),
  confirmation_token: z.string(),
  expires_at: isoDate,
  candidate_id: z.string(),
  expected_version: z.number().int(),
  impact: z.object({
    will_create_internal_event: z.boolean(),
    will_write_external_calendar: z.boolean(),
    will_queue_notification: z.boolean(),
    event_title: z.string(),
    start_at: isoDate,
    end_at: isoDate,
    timezone: z.string(),
  }).passthrough(),
});

export const calendarEventSchema = z.object({
  id: z.string(),
  candidate_id: z.string(),
  plan_id: z.string(),
  course_id: z.string(),
  title: z.string(),
  action_type: z.string(),
  target_id: z.string(),
  start_at: isoDate,
  end_at: isoDate,
  timezone: z.string(),
  status: z.string(),
  version: z.number().int(),
  created_at: isoDate,
  updated_at: isoDate,
  cancelled_at: isoDate.nullable(),
  completed_at: isoDate.nullable(),
});
export const calendarEventsSchema = z.array(calendarEventSchema);

export const studyPreferenceSchema = z.object({
  id: z.string(),
  course_id: z.string(),
  timezone: z.string(),
  available_time: z.array(z.object({
    weekday: z.number().int().min(0).max(6),
    start: z.string(),
    end: z.string(),
  })),
  preferred_duration_min: z.number().int(),
  version: z.number().int(),
  created_at: isoDate,
  updated_at: isoDate,
});

export const notificationPreferenceSchema = z.object({
  id: z.string(),
  course_id: z.string(),
  enabled: z.boolean(),
  channel: z.enum(["in_app", "webhook"]),
  lead_minutes: z.number().int(),
  version: z.number().int(),
  created_at: isoDate,
  updated_at: isoDate,
});

export const notificationDeliverySchema = z.object({
  id: z.string(),
  course_id: z.string(),
  calendar_event_id: z.string(),
  channel: z.string(),
  template_id: z.string(),
  status: z.string(),
  scheduled_at: isoDate,
  delivered_at: isoDate.nullable(),
  error_code: z.string().nullable(),
  created_at: isoDate,
});
export const notificationDeliveriesSchema = z.array(notificationDeliverySchema);

export const feedbackSchema = z.object({
  id: z.string(),
  course_id: z.string(),
  target_type: z.string(),
  target_id: z.string(),
  target_version_id: z.string().nullable(),
  action: z.enum(["report", "hide", "correct"]),
  reason_code: z.string(),
  detail: z.string().nullable(),
  correction: z.record(z.string(), z.unknown()),
  status: z.string(),
  resolution_note: z.string().nullable(),
  version: z.number().int(),
  created_at: isoDate,
  updated_at: isoDate,
});
export const feedbackListSchema = z.array(feedbackSchema);

export const workflowRunSchema = z.object({
  id: z.string(),
  task_type: z.string(),
  course_id: z.string(),
  status: z.string(),
  scope_snapshot: z.record(z.string(), z.unknown()),
  policy_versions: z.record(z.string(), z.unknown()),
  started_at: isoDate,
  finished_at: isoDate.nullable(),
  events: z.array(z.object({
    id: z.string(),
    event_type: z.string(),
    message: z.string(),
    created_at: isoDate,
  }).passthrough()),
  jobs: z.array(z.object({
    id: z.string(),
    job_type: z.string(),
    status: z.string(),
  }).passthrough()),
});

export type ReviewPlan = z.infer<typeof reviewPlanSchema>;
export type CalendarCandidate = z.infer<typeof calendarCandidateSchema>;
export type ConfirmationPreview = z.infer<typeof confirmationPreviewSchema>;
export type CalendarEvent = z.infer<typeof calendarEventSchema>;
export type NotificationPreference = z.infer<typeof notificationPreferenceSchema>;
