import { describe, expect, it } from "vitest";

import { acceptanceChecks, qualityGates } from "@/features/acceptance/checks";

describe("F6 final frontend quality contract", () => {
  it("keeps the product-manager acceptance list aligned to the twelve manual steps", () => {
    expect(acceptanceChecks).toHaveLength(12);
    expect(new Set(acceptanceChecks.map((item) => item.id)).size).toBe(12);
  });

  it("uses only local application paths for acceptance deep links", () => {
    const links = acceptanceChecks.flatMap((item) => item.href ? [item.href] : []);
    expect(links.length).toBeGreaterThan(0);
    expect(links.every((href) => href.startsWith("/") && !href.startsWith("//"))).toBe(true);
  });

  it("records every required automated gate without claiming real integration", () => {
    expect(qualityGates.join(" ")).toContain("ESLint");
    expect(qualityGates.join(" ")).toContain("TypeScript");
    expect(qualityGates.join(" ")).toContain("Vitest");
    expect(qualityGates.join(" ")).toContain("Playwright");
    expect(qualityGates.join(" ")).toContain("生产构建");
  });
});
