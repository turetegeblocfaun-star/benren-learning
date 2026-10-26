"use client";

import { CalendarCheck2, CalendarX2, CheckCircle2, Download, History, RotateCcw } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { LoadingCard, Notice } from "@/components/Feedback";
import { F4Shell, StateLabel, formatPlanTime } from "@/components/planning/F4Shell";
import { calendarEventSchema, calendarEventsSchema, type CalendarEvent } from "@/features/planning/schema";
import { reviewPlanListSchema } from "@/features/system/schema";
import { apiFetchContract, idempotencyKey, presentError } from "@/lib/api/client";

export default function InternalCalendarPage() {
  const { courseId } = useParams<{ courseId: string }>();
  const queryClient = useQueryClient();
  const [message, setMessage] = useState("");
  const events = useQuery({ queryKey: ["f4-calendar", courseId], queryFn: () => apiFetchContract(calendarEventsSchema, `/api/v1/courses/${courseId}/calendar-events`) });
  const plans = useQuery({ queryKey: ["review-plans", courseId], queryFn: () => apiFetchContract(reviewPlanListSchema, `/api/v1/courses/${courseId}/review-plans?limit=100`) });
  const planId = plans.data?.find((item) => item.status !== "failed")?.id;
  const change = useMutation({
    mutationFn: ({ event, operation }: { event: CalendarEvent; operation: "undo" | "complete" }) => apiFetchContract(calendarEventSchema, `/api/v1/calendar-events/${event.id}/${operation}`, {
      method: "POST", headers: { "If-Match": String(event.version), "Idempotency-Key": idempotencyKey(`calendar-${operation}`) },
    }),
    onSuccess: async (event) => { setMessage(event.status === "cancelled" ? "已撤销安排；历史仍保留，没有删除。" : "已完成复习；计划状态会据此推进。"); await queryClient.invalidateQueries({ queryKey: ["f4-calendar", courseId] }); },
  });

  return (
    <F4Shell eyebrow="F4 · 内部日历" title="你的安排，保留完整来路" description="这里只显示你明确确认过的内部日历事件。完成与撤销都会追加状态，原始安排不会被删除。" backHref={`/courses/${courseId}/workspace`}>
      {message ? <div className="f4-feedback-space"><Notice tone="success" message={message} /></div> : null}
      {change.error ? <div className="f4-feedback-space"><Notice tone="error" {...presentError(change.error)} /></div> : null}
      {events.isPending ? <LoadingCard label="正在读取内部日历历史…" /> : events.error ? <Notice tone="error" {...presentError(events.error)} /> : events.data?.length === 0 ? (
        <section className="f4-empty-state"><CalendarX2 size={32} /><h2>还没有内部日历事件</h2><p>生成候选时间不会写入。请先查看影响并明确确认。</p>{planId ? <Link className="button button-primary" href={`/courses/${courseId}/plans/${planId}`}>去确认计划</Link> : <Link className="button button-primary" href={`/courses/${courseId}/workspace`}>先生成计划</Link>}</section>
      ) : (
        <section className="f4-calendar-list" aria-label="内部日历历史">
          {events.data?.map((event) => (
            <article className="f4-calendar-event" key={event.id}>
              <div className="f4-calendar-date"><strong>{new Intl.DateTimeFormat("zh-CN", { day: "2-digit", timeZone: "Asia/Shanghai" }).format(new Date(event.start_at))}</strong><span>{new Intl.DateTimeFormat("zh-CN", { month: "short", timeZone: "Asia/Shanghai" }).format(new Date(event.start_at))}</span></div>
              <div className="f4-calendar-main"><div className="cluster"><StateLabel status={event.status} /><small>事件 v{event.version}</small></div><h2>{event.title}</h2><p>{formatPlanTime(event.start_at)} — {new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Shanghai" }).format(new Date(event.end_at))} · {event.timezone}</p><p className="f4-history-note"><History size={14} />{event.status === "cancelled" ? "撤销时间已记录，原事件仍在历史中。" : event.status === "completed" ? "完成时间已记录，可导出原安排。" : "来自一次性确认；外部日历没有被写入。"}</p></div>
              <div className="f4-calendar-actions">
                <a className="button button-secondary" href={`/api/v1/calendar-events/${event.id}.ics`} download><Download size={15} />导出 ICS</a>
                {event.status === "scheduled" ? <><button className="button button-primary" onClick={() => change.mutate({ event, operation: "complete" })} disabled={change.isPending}><CheckCircle2 size={15} />标记完成</button><button className="f4-danger-link" onClick={() => change.mutate({ event, operation: "undo" })} disabled={change.isPending}><RotateCcw size={15} />撤销安排</button></> : null}
              </div>
            </article>
          ))}
        </section>
      )}
      <section className="f4-calendar-rule"><CalendarCheck2 size={19} /><div><strong>F4 只维护内部日历</strong><p>ICS 是下载文件，由你自行导入；Google、Apple 等外部日历连接属于后续受控阶段。</p></div></section>
    </F4Shell>
  );
}
