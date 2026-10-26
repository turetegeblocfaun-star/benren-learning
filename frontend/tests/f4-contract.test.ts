import { describe, expect, it } from "vitest";

import { calendarEventSchema, confirmationPreviewSchema, workflowRunSchema } from "@/features/planning/schema";

describe("F4 planning contracts", () => {
  it("requires confirmation preview to state internal and external effects", () => {
    const base = {
      confirmation_id: "confirmation", confirmation_token: "opaque", expires_at: "2026-09-01T10:10:00Z",
      candidate_id: "candidate", expected_version: 2,
      impact: { will_create_internal_event: true, will_queue_notification: true, event_title: "复习", start_at: "2026-09-02T10:00:00Z", end_at: "2026-09-02T10:30:00Z", timezone: "Asia/Shanghai" },
    };
    expect(confirmationPreviewSchema.safeParse(base).success).toBe(false);
    expect(confirmationPreviewSchema.parse({ ...base, impact: { ...base.impact, will_write_external_calendar: false } }).impact.will_write_external_calendar).toBe(false);
  });

  it("keeps cancelled calendar events as versioned history", () => {
    const value = calendarEventSchema.parse({
      id: "event", candidate_id: "candidate", plan_id: "plan", course_id: "course", title: "复习", action_type: "note_review",
      target_id: "note", start_at: "2026-09-02T10:00:00Z", end_at: "2026-09-02T10:30:00Z", timezone: "Asia/Shanghai",
      status: "cancelled", version: 2, created_at: "2026-09-01T10:00:00Z", updated_at: "2026-09-01T10:05:00Z",
      cancelled_at: "2026-09-01T10:05:00Z", completed_at: null,
    });
    expect(value.status).toBe("cancelled");
    expect(value.cancelled_at).not.toBeNull();
  });

  it("accepts redacted workflow scope without raw prompts or secrets", () => {
    const value = workflowRunSchema.parse({
      id: "run", task_type: "review_plan_generation", course_id: "course", status: "completed",
      scope_snapshot: { raw_material_text: "[REDACTED]", secret_fields_removed: true }, policy_versions: { privacy: "v2" },
      started_at: "2026-09-01T10:00:00Z", finished_at: "2026-09-01T10:01:00Z",
      events: [{ id: "event", event_type: "scope_locked", message: "范围已冻结", created_at: "2026-09-01T10:00:00Z" }],
      jobs: [{ id: "job", job_type: "review_plan_generation", status: "completed" }],
    });
    expect(value.scope_snapshot.raw_material_text).toBe("[REDACTED]");
    expect(JSON.stringify(value)).not.toMatch(/api[_-]?key|authorization|system_prompt/i);
  });
});
