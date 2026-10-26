export type UiTone = "neutral" | "running" | "warning" | "success" | "danger";

const MATERIAL_STATUS: Record<string, { label: string; tone: UiTone }> = {
  pending: { label: "等待上传", tone: "neutral" },
  uploading: { label: "正在上传", tone: "running" },
  extracting: { label: "正在识别", tone: "running" },
  needs_review: { label: "需要你校正", tone: "warning" },
  usable: { label: "可以使用", tone: "success" },
  partial: { label: "部分可用", tone: "warning" },
  failed: { label: "处理失败", tone: "danger" },
  deleting: { label: "正在删除", tone: "running" },
  deleted: { label: "已删除", tone: "neutral" },
};

export function materialStatus(status: string): { label: string; tone: UiTone } {
  return MATERIAL_STATUS[status] ?? { label: "状态待确认", tone: "neutral" };
}

export function materialTypeLabel(type: string): string {
  return (
    {
      audio: "课堂录音",
      text: "文本材料",
      board_image: "板书图片",
      handwriting_image: "手写笔记",
    }[type] ?? "学习材料"
  );
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function locatorLabel(value: {
  start_ms: number | null;
  end_ms: number | null;
  page_no: number | null;
  paragraph_no: number | null;
}): string {
  if (value.start_ms !== null) {
    const start = Math.floor(value.start_ms / 1000);
    const end = Math.floor((value.end_ms ?? value.start_ms) / 1000);
    return `${Math.floor(start / 60)}:${String(start % 60).padStart(2, "0")}–${Math.floor(end / 60)}:${String(end % 60).padStart(2, "0")}`;
  }
  if (value.page_no !== null) return `第 ${value.page_no} 页`;
  if (value.paragraph_no !== null) return `第 ${value.paragraph_no} 段`;
  return "原文位置";
}
