import { describe, expect, it } from "vitest";

import { controlledGateContract } from "@/features/controlled/gates";
import { organizationAggregateSchema, subjectiveAssessmentSchema } from "@/features/controlled/schema";

describe("F5 controlled capability contracts", () => {
  it("never accepts an automatic correctness value for subjective self-assessment", () => {
    const base = { id: "assessment", exercise_id: "exercise", response_text: "解释", rubric_ratings: [{ criterion_id: "concept", rating: 4, evidence_note: "材料依据" }], reflection: "继续补充", confidence: 4, created_at: "2026-09-01T00:00:00Z" };
    expect(subjectiveAssessmentSchema.safeParse({ ...base, automatic_correctness: true }).success).toBe(false);
    expect(subjectiveAssessmentSchema.parse({ ...base, automatic_correctness: null }).automatic_correctness).toBeNull();
  });

  it("requires organization aggregate responses to exclude raw learning content", () => {
    const base = { organization_id: "org", learner_count: 1, group_count: 1, assigned_course_count: 1, completed_review_count: 1, attempted_question_count: 2 };
    expect(organizationAggregateSchema.safeParse({ ...base, raw_learning_content_included: true }).success).toBe(false);
    expect(organizationAggregateSchema.parse({ ...base, raw_learning_content_included: false }).raw_learning_content_included).toBe(false);
  });

  it("maps every controlled page to a server-issued capability", () => {
    expect(controlledGateContract.practice.capability).toBe("practice:subjective");
    expect(controlledGateContract.organization.capability).toBe("organization:manage");
    expect(controlledGateContract.sft.capability).toBe("sft:manage");
    expect(controlledGateContract.governance.capability).toBe("governance:read");
  });
});
