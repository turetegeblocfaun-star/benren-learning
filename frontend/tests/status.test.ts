import { describe, expect, it } from "vitest";

import { formatBytes, locatorLabel, materialStatus, materialTypeLabel } from "@/lib/status";

describe("product-facing status mapping", () => {
  it("does not treat an unknown backend status as success", () => {
    expect(materialStatus("new-provider-status")).toEqual({
      label: "状态待确认",
      tone: "neutral",
    });
  });

  it("maps review and file details into readable Chinese", () => {
    expect(materialStatus("needs_review").label).toBe("需要你校正");
    expect(materialTypeLabel("handwriting_image")).toBe("手写笔记");
    expect(formatBytes(2 * 1024 * 1024)).toBe("2.0 MB");
    expect(locatorLabel({ start_ms: 65_000, end_ms: 70_000, page_no: null, paragraph_no: null })).toBe(
      "1:05–1:10",
    );
  });
});
