import { describe, expect, it } from "vitest";

import { noteContentSchema, quizSchema, tutorSessionSchema } from "@/features/learning/schema";

describe("F3 learning contracts", () => {
  it("accepts the five required note provenance layers", () => {
    const result = noteContentSchema.safeParse({
      title: "结构化笔记",
      summary: "概要",
      sections: [
        ["uploaded_material", ["source-1"]],
        ["material_example", ["source-2"]],
        ["official_supplement", []],
        ["ai_inference", ["source-2"]],
        ["needs_review", ["source-3"]],
      ].map(([provenance, refs], index) => ({ id: `s${index}`, title: `区块${index}`, body: "内容", provenance, source_ref_ids: refs })),
    });
    expect(result.success).toBe(true);
  });

  it("rejects leaked answers in the quiz read contract", () => {
    const result = quizSchema.safeParse({
      id: "quiz", course_id: "course", context_snapshot_id: "snapshot", status: "ready", difficulty: "medium",
      requested_count: 1, published_count: 1, withdrawn_question_ids: [], error_code: null, error_message: null,
      questions: [{
        id: "question", version_no: 1, type: "single_choice", stem: "题干", options: [{ id: "A", text: "选项" }],
        concept_ids: [], source_ref_ids: ["source"], status: "active", correct_answer: "A",
      }], created_at: "2026-08-31T00:00:00Z", updated_at: "2026-08-31T00:00:00Z",
    });
    expect(result.success).toBe(false);
  });

  it("keeps legacy, indexed-full and retrieval modes as backend-owned values", () => {
    const base = {
      id: "session", course_id: "course", context_snapshot_id: "snapshot", learning_goal: "理解", target_problem: null,
      fsm_state: "diagnose", status: "active", turn_count: 0, max_turns: 8, version: 1, turns: [],
      created_at: "2026-08-31T00:00:00Z", updated_at: "2026-08-31T00:00:00Z", ended_at: null,
    };
    expect(tutorSessionSchema.parse({ ...base, context_mode: "direct_full" }).context_mode).toBe("direct_full");
    expect(tutorSessionSchema.parse({ ...base, context_mode: "indexed_full" }).context_mode).toBe("indexed_full");
    expect(tutorSessionSchema.parse({ ...base, context_mode: "tutor_rag" }).context_mode).toBe("tutor_rag");
    expect(tutorSessionSchema.safeParse({ ...base, context_mode: "user_selected" }).success).toBe(false);
  });
});
