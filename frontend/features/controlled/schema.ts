import { z } from "zod";

const iso = z.string();

export const subjectiveExerciseSchema = z.object({
  id: z.string(), course_id: z.string(), context_snapshot_id: z.string(), prompt: z.string(),
  rubric: z.array(z.object({ id: z.string(), label: z.string(), description: z.string() }).passthrough()),
  source_ref_ids: z.array(z.string()), status: z.string(), model_id: z.string(), prompt_version: z.string(), created_at: iso,
});
export const subjectiveExerciseListSchema = z.array(subjectiveExerciseSchema);
export const subjectiveAssessmentSchema = z.object({
  id: z.string(), exercise_id: z.string(), response_text: z.string(),
  rubric_ratings: z.array(z.object({ criterion_id: z.string(), rating: z.number().int(), evidence_note: z.string() }).passthrough()),
  reflection: z.string(), confidence: z.number().int(), automatic_correctness: z.null(), created_at: iso,
});
export const adaptiveReviewSchema = z.object({
  id: z.string(), course_id: z.string(), interval_days: z.number().int(), next_review_at: iso,
  evidence: z.record(z.string(), z.unknown()), explanation: z.string(), algorithm_version: z.string(), updated_at: iso,
});

export const externalAuthorizationSchema = z.object({
  connection_id: z.string(), provider: z.string(), authorization_url: z.string(), status: z.string(), scopes: z.array(z.string()),
});
export const externalConnectionSchema = z.object({
  id: z.string(), provider: z.string(), status: z.string(), scopes: z.array(z.string()),
  external_account_ref: z.string().nullable(), expires_at: iso.nullable(), version: z.number().int(),
});
export const externalSyncSchema = z.object({
  id: z.string(), connection_id: z.string(), calendar_event_id: z.string(), status: z.string(), direction: z.string(),
  pending_change: z.record(z.string(), z.unknown()), external_event_id: z.string().nullable(), error_code: z.string().nullable(), version: z.number().int(),
});
export const externalSyncConfirmationSchema = z.object({
  confirmation_token: z.string(), expires_at: iso,
  impact: z.object({ direction: z.string(), will_write_external_calendar: z.boolean(), will_update_internal_calendar: z.boolean(), pending_change: z.record(z.string(), z.unknown()), can_undo: z.boolean() }),
});

export const organizationSchema = z.object({
  id: z.string(), name: z.string(), owner_user_id: z.string(), current_user_role: z.string(), created_at: iso,
});
export const organizationListSchema = z.array(organizationSchema);
export const groupSchema = z.object({ id: z.string(), organization_id: z.string(), name: z.string(), member_count: z.number().int(), created_at: iso });
export const groupListSchema = z.array(groupSchema);
export const organizationMemberSchema = z.object({ membership_id: z.string(), user_id: z.string(), role: z.string(), created_at: iso });
export const organizationMemberListSchema = z.array(organizationMemberSchema);
export const courseAssignmentSchema = z.object({
  assignment_id: z.string(), group_id: z.string(), course_id: z.string(), due_at: iso.nullable(), created_at: iso, version: z.number().int(),
});
export const courseAssignmentListSchema = z.array(courseAssignmentSchema);
export const organizationAggregateSchema = z.object({
  organization_id: z.string(), learner_count: z.number().int(), group_count: z.number().int(), assigned_course_count: z.number().int(),
  completed_review_count: z.number().int(), attempted_question_count: z.number().int(), raw_learning_content_included: z.literal(false),
});
export const genericRecordSchema = z.record(z.string(), z.unknown());
export const crossCourseLinkSchema = z.object({
  id: z.string(), source_course_id: z.string(), target_course_id: z.string(), selected_source_ref_ids: z.array(z.string()),
  purpose: z.string(), status: z.string(), version: z.number().int(), created_at: iso, revoked_at: iso.nullable(),
});
export const crossCourseLinkListSchema = z.array(crossCourseLinkSchema);

export const sftProjectSchema = z.object({
  id: z.string(), name: z.string(), use_case: z.string(), baseline_metric_name: z.string(), baseline_score: z.number(), target_score: z.number(),
  status: z.string(), provider_job_id: z.string().nullable(), gate_report: z.record(z.string(), z.unknown()), created_at: iso, updated_at: iso,
});
export const sftProjectListSchema = z.array(sftProjectSchema);
export const sftConsentSchema = z.object({ consent_id: z.string(), status: z.string(), source_ref_id: z.string() });
export const sftDatasetSchema = z.object({ dataset_snapshot_id: z.string(), record_count: z.number().int(), content_hash: z.string(), status: z.string() });
export const sftEvaluationSchema = z.object({ evaluation_id: z.string(), gate_report: z.record(z.string(), z.unknown()) });

export const governanceMetricsSchema = z.object({
  generated_at: iso, workflow_runs: z.record(z.string(), z.number()), jobs: z.record(z.string(), z.number()),
  guardrails: z.record(z.string(), z.number()), feedback: z.record(z.string(), z.number()), external_adapters: z.record(z.string(), z.string()),
  performance: z.record(z.string(), z.unknown()), alerts: z.array(z.record(z.string(), z.unknown())),
});

export type SubjectiveExercise = z.infer<typeof subjectiveExerciseSchema>;
export type SubjectiveAssessment = z.infer<typeof subjectiveAssessmentSchema>;
export type ExternalConnection = z.infer<typeof externalConnectionSchema>;
export type ExternalSync = z.infer<typeof externalSyncSchema>;
export type ExternalSyncConfirmation = z.infer<typeof externalSyncConfirmationSchema>;
export type CrossCourseLink = z.infer<typeof crossCourseLinkSchema>;
export type SftProject = z.infer<typeof sftProjectSchema>;
