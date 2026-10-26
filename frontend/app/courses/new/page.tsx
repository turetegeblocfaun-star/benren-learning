"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { LoadingCard, Notice } from "@/components/Feedback";
import { courseSchema } from "@/features/materials/schema";
import { AppError, apiFetchContract, jsonBody, presentError } from "@/lib/api/client";

const DEFAULT_WORKSPACE_KEY = "default-material-workspace-v1";

export default function OpenWorkspacePage() {
  const router = useRouter();
  const started = useRef(false);
  const [error, setError] = useState<{ message: string; detail?: string } | null>(null);

  const openWorkspace = useCallback(async () => {
    setError(null);
    try {
      const course = await apiFetchContract(courseSchema, "/api/v1/courses", {
        method: "POST",
        headers: { "Idempotency-Key": DEFAULT_WORKSPACE_KEY },
        body: jsonBody({ temporary_title: null }),
      });
      localStorage.setItem(
        "bl_recent_course",
        JSON.stringify({
          id: course.id,
          title: course.title ?? "未命名课程",
          savedAt: new Date().toISOString(),
        }),
      );
      router.replace(`/courses/${course.id}/materials`);
    } catch (caught) {
      if (caught instanceof AppError && caught.status === 401) {
        router.replace("/login?next=/courses/new");
        return;
      }
      setError(presentError(caught));
    }
  }, [router]);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void openWorkspace();
  }, [openWorkspace]);

  return (
    <AppShell>
      <main className="page-narrow">
        {error ? (
          <section className="card stack">
            <Notice tone="error" {...error} />
            <button className="button button-primary" onClick={() => void openWorkspace()}>
              重新打开材料工作台
            </button>
          </section>
        ) : (
          <LoadingCard label="正在打开资料上传页…" />
        )}
      </main>
    </AppShell>
  );
}
