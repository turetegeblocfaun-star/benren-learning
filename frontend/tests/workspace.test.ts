import { describe, expect, it } from "vitest";

import { workspaceResponseSchema } from "@/features/workspace/schema";

describe("workspace contract boundary", () => {
  const baseResponse = {
    course_id: "course-1",
    action: {
      type: "note_review",
      target_id: "note-1",
      reason: "笔记已经可以复习",
      duration_min: 12,
      plan_id: null,
    },
    derived_by: "workflow",
  };

  it("accepts a documented workspace action", () => {
    expect(workspaceResponseSchema.parse(baseResponse).action.type).toBe("note_review");
  });

  it("rejects an unknown action instead of silently rendering it", () => {
    const result = workspaceResponseSchema.safeParse({
      ...baseResponse,
      action: { ...baseResponse.action, type: "surprise_action" },
    });
    expect(result.success).toBe(false);
  });
});
