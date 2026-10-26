import { describe, expect, it } from "vitest";

import { materialSchema, sourceRefSchema } from "@/features/materials/schema";

describe("F2 material contracts", () => {
  it("accepts an unknown backend status without pretending it succeeded", () => {
    const parsed = materialSchema.parse({
      id: "m1",
      course_id: "c1",
      batch_id: "b1",
      declared_type: "text",
      detected_type: "text",
      display_name: "课堂材料.txt",
      detected_mime: "text/plain",
      byte_size: 12,
      status: "future_provider_state",
      active_parse_version_id: null,
      error_code: null,
      error_message: null,
      retryable: false,
      version: 1,
      created_at: "2026-08-31T00:00:00Z",
      updated_at: "2026-08-31T00:00:00Z",
      jobs: [],
    });
    expect(parsed.status).toBe("future_provider_state");
  });

  it("rejects a source reference without a traceable locator shape", () => {
    const result = sourceRefSchema.safeParse({ id: "source-only" });
    expect(result.success).toBe(false);
  });
});
