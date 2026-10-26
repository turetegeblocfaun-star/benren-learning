import type { UiTone } from "@/lib/status";

export function StatusChip({ label, tone }: { label: string; tone: UiTone }) {
  return <span className={`status-chip tone-${tone}`}>{label}</span>;
}
