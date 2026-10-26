"use client";

import { CalendarCheck2, Check, Clock3, ShieldAlert, X } from "lucide-react";
import { useEffect, useRef, type RefObject } from "react";

import type { ConfirmationPreview } from "@/features/planning/schema";
import { formatPlanTime } from "./F4Shell";

export function ConfirmationDialog({ preview, busy, onClose, onConfirm, returnFocusRef }: {
  preview: ConfirmationPreview;
  busy: boolean;
  onClose: () => void;
  onConfirm: () => void;
  returnFocusRef?: RefObject<HTMLElement | null>;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const latestRef = useRef({ busy, onClose });

  useEffect(() => {
    latestRef.current = { busy, onClose };
  }, [busy, onClose]);

  useEffect(() => {
    const previous = returnFocusRef?.current ?? document.activeElement as HTMLElement | null;
    dialogRef.current?.focus();
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !latestRef.current.busy) latestRef.current.onClose();
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ));
      if (!focusable.length) {
        event.preventDefault();
        dialogRef.current.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handler);
    return () => { document.removeEventListener("keydown", handler); previous?.focus(); };
  }, [returnFocusRef]);

  return (
    <div className="f4-dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose(); }}>
      <div className="f4-dialog" role="dialog" aria-modal="true" aria-labelledby="confirm-title" aria-describedby="confirm-description" tabIndex={-1} ref={dialogRef}>
        <button className="f4-dialog-close" type="button" onClick={onClose} disabled={busy} aria-label="关闭确认窗口"><X size={18} /></button>
        <span className="f4-dialog-icon"><CalendarCheck2 size={25} /></span>
        <p className="eyebrow">写入前影响预览</p>
        <h2 id="confirm-title">确认后才会写入内部日历</h2>
        <p className="muted" id="confirm-description">本次确认只对候选时间 v{preview.expected_version} 生效，并且只能使用一次。</p>
        <dl className="f4-impact-list">
          <div><dt><Clock3 size={15} />时间</dt><dd>{formatPlanTime(preview.impact.start_at)}，约 30 分钟</dd></div>
          <div><dt><Check size={15} />内部日历</dt><dd>将新增 1 条“{preview.impact.event_title}”</dd></div>
          <div><dt><Check size={15} />站内通知</dt><dd>{preview.impact.will_queue_notification ? "将按当前偏好进入等待队列" : "本次不创建通知"}</dd></div>
          <div><dt><ShieldAlert size={15} />外部日历</dt><dd>不会写入；F4 未连接任何外部账号</dd></div>
        </dl>
        <div className="f4-dialog-actions">
          <button className="button button-secondary" type="button" onClick={onClose} disabled={busy}>再想想</button>
          <button className="button button-primary" type="button" onClick={onConfirm} disabled={busy}>{busy ? "正在确认…" : "确认并写入内部日历"}</button>
        </div>
        <p className="f4-expiry">确认有效期至 {formatPlanTime(preview.expires_at)}；修改时间后必须重新预览。</p>
      </div>
    </div>
  );
}
