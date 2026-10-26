"use client";

import { AlertTriangle } from "lucide-react";
import { useEffect, useRef } from "react";

export function DeleteDialog({
  name,
  impact,
  busy,
  onCancel,
  onConfirm,
}: {
  name: string;
  impact: Record<string, unknown>;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLElement>(null);
  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onCancel();
      if (event.key !== "Tab" || !dialogRef.current) return;
      const controls = Array.from(dialogRef.current.querySelectorAll<HTMLElement>("button:not(:disabled), [href], input:not(:disabled)"));
      if (!controls.length) return;
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKeyDown);
    cancelRef.current?.focus();
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      previousFocus?.focus();
    };
  }, [busy, onCancel]);
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onCancel(); }}>
      <section ref={dialogRef} className="modal" role="dialog" aria-modal="true" aria-labelledby="delete-title" aria-describedby="delete-description">
        <div className="cluster"><AlertTriangle color="var(--danger)" aria-hidden="true" /><h2 id="delete-title" style={{ margin: 0 }}>确认删除这份材料？</h2></div>
        <p id="delete-description" className="muted">“{name}”删除后不能继续参与新的学习任务。</p>
        <div className="subtle-card small">
          <strong>删除会产生这些影响</strong>
          <ul className="delete-impact-list">
            <li>原件和解析版本将进入删除流程。</li>
            <li>这份材料的来源链接将失效。</li>
            <li>{Number(impact.context_snapshots_may_become_stale ?? 0) > 0 ? `已有 ${String(impact.context_snapshots_may_become_stale)} 个上下文快照可能需要重新生成。` : "目前没有已生成的上下文快照受到影响。"}</li>
          </ul>
        </div>
        <div className="modal-actions">
          <button ref={cancelRef} className="button button-secondary" onClick={onCancel} disabled={busy}>保留材料</button>
          <button className="button button-danger" onClick={onConfirm} disabled={busy}>{busy ? "正在删除…" : "确认删除"}</button>
        </div>
      </section>
    </div>
  );
}
