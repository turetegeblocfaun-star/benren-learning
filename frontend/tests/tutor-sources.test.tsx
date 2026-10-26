import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TutorSources } from "@/components/learning/TutorSources";
import { apiFetchContract } from "@/lib/api/client";

vi.mock("@/lib/api/client", () => ({ apiFetchContract: vi.fn() }));
const fetchSource = vi.mocked(apiFetchContract);

function show(ids: string[], kind: "cited" | "material_scope" = "cited") {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <TutorSources sourceIds={ids} kind={kind} />
  </QueryClientProvider>);
}

function expand(container: HTMLElement) {
  const details = container.querySelector("details")!;
  details.open = true;
  fireEvent(details, new Event("toggle"));
}

describe("Tutor citation display", () => {
  beforeEach(() => {
    fetchSource.mockReset();
    fetchSource.mockResolvedValue({
      id: "src_1", material_id: "mat_1", material_version_id: "ver_1",
      display_name: "B1 听力样题.pdf", material_type: "text", text: "There are four parts to the test.",
      locator_type: "page", page_no: 1, paragraph_no: null, start_ms: null, end_ms: null,
      bbox: null, confidence: null, preview_path: "/original",
    });
  });

  it("collapses and deduplicates 52 sources without fetching them on entry", () => {
    show([...Array.from({ length: 52 }, (_, i) => `src_${i}`), "src_1"]);
    expect(screen.getByText("查看本轮引用（52 处）")).toBeVisible();
    expect(screen.queryAllByRole("link")).toHaveLength(0);
    expect(fetchSource).not.toHaveBeenCalled();
  });

  it("loads only six previews at a time with readable filenames and page locations", async () => {
    const { container } = show(Array.from({ length: 52 }, (_, i) => `src_${i}`));
    expand(container);
    await waitFor(() => expect(screen.getAllByText("第 1 页")).toHaveLength(6));
    expect(screen.getAllByRole("link")).toHaveLength(6);
    expect(fetchSource).toHaveBeenCalledTimes(6);
    expect(screen.getAllByText("B1 听力样题.pdf")).toHaveLength(6);
    expect(screen.getAllByText("There are four parts to the test.")).toHaveLength(6);
    fireEvent.click(screen.getByRole("button", { name: "再显示 6 处来源" }));
    await waitFor(() => expect(fetchSource).toHaveBeenCalledTimes(12));
  });

  it("labels ambiguous historic evidence as material scope rather than actual citations", async () => {
    const { container } = show(["src_1"], "material_scope");
    expect(screen.getByText("查看材料范围（1 段）")).toBeVisible();
    expand(container);
    expect(screen.getByText(/这条历史回复未记录具体引用/)).toBeVisible();
    await screen.findByText("第 1 页");
  });

  it("keeps a working source-page link when an individual preview fails", async () => {
    fetchSource.mockRejectedValue(new Error("permission denied"));
    const { container } = show(["src_1"]);
    expand(container);
    await screen.findByText("暂时无法读取预览，可进入来源页重试。");
    expect(screen.getByRole("link")).toHaveAttribute("href", "/sources/src_1");
    expect(screen.queryByText("src_1")).not.toBeInTheDocument();
  });
});
