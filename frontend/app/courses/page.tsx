"use client";

import { ArrowRight, BookOpenCheck, FileUp, History } from "lucide-react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { AppShell } from "@/components/AppShell";
import { LoadingCard, Notice } from "@/components/Feedback";
import { courseListSchema } from "@/features/system/schema";
import { apiFetchContract, presentError } from "@/lib/api/client";

export default function CourseHistoryPage() {
  const courses = useQuery({
    queryKey: ["courses"],
    queryFn: () => apiFetchContract(courseListSchema, "/api/v1/courses?limit=100"),
  });

  return (
    <AppShell>
      <main className="page-wrap course-history-page">
        <div className="page-head">
          <div className="page-head-copy">
            <p className="eyebrow">课程记录</p>
            <h1>从你真实上传过的内容继续</h1>
            <p className="lede">课程名称和学习内容来自上传材料，不预置学科，也不依赖浏览器里写死的资源 ID。</p>
          </div>
          <Link className="button button-primary" href="/courses/new"><FileUp size={16} />上传新资料</Link>
        </div>
        {courses.isPending ? <LoadingCard label="正在读取课程记录…" /> : courses.error ? <Notice tone="error" {...presentError(courses.error)} /> : courses.data?.length ? (
          <div className="course-history-grid">
            {courses.data.map((course) => (
              <article key={course.id}>
                <History size={19} />
                <small>{course.title_status === "confirmed" ? "名称已确认" : "等待根据材料确认名称"}</small>
                <h2>{course.title ?? "未命名课程"}</h2>
                <p>可用材料 {course.material_counts.usable ?? 0} 份 · 待核对 {course.material_counts.needs_review ?? 0} 份</p>
                <div className="cluster">
                  <Link className="button button-secondary button-small" href={`/courses/${course.id}/materials`}><FileUp size={14} />材料</Link>
                  <Link className="button button-primary button-small" href={`/courses/${course.id}/workspace`}><BookOpenCheck size={14} />继续学习 <ArrowRight size={14} /></Link>
                </div>
              </article>
            ))}
          </div>
        ) : <section className="empty-card"><BookOpenCheck size={28} /><h2>还没有课程</h2><p>先上传资料，系统读取内容后再由你确认课程名称。</p><Link className="button button-primary" href="/courses/new">去上传资料</Link></section>}
      </main>
    </AppShell>
  );
}
