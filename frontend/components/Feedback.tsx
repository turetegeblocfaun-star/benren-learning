import { AlertCircle, CheckCircle2, Info, Inbox } from "lucide-react";

export function Notice({
  tone = "info",
  message,
  detail,
}: {
  tone?: "error" | "info" | "success";
  message: string;
  detail?: string;
}) {
  const Icon = tone === "error" ? AlertCircle : tone === "success" ? CheckCircle2 : Info;
  return (
    <div className={`notice notice-${tone}`} role={tone === "error" ? "alert" : "status"}>
      <Icon size={18} aria-hidden="true" />
      <div><p>{message}</p>{detail ? <p className="small">{detail}</p> : null}</div>
    </div>
  );
}

export function EmptyState({ title, text }: { title: string; text: string }) {
  return (
    <div className="empty-state">
      <div className="empty-icon" aria-hidden="true"><Inbox size={24} /></div>
      <h3>{title}</h3><p>{text}</p>
    </div>
  );
}

export function LoadingCard({ label = "正在读取真实数据…" }: { label?: string }) {
  return (
    <div className="card" aria-busy="true" aria-live="polite">
      <p className="muted small">{label}</p>
      <div className="stack"><div className="skeleton" /><div className="skeleton" style={{ width: "72%" }} /><div className="skeleton" style={{ width: "88%" }} /></div>
    </div>
  );
}
