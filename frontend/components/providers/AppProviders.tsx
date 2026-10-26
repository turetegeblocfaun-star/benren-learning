"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useEffect, useState } from "react";

function MockGate({ children }: { children: ReactNode }) {
  const mockEnabled = process.env.NEXT_PUBLIC_API_MODE === "mock";
  const [ready, setReady] = useState(!mockEnabled);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!mockEnabled) return;

    let active = true;
    void import("@/mocks/browser")
      .then(({ startMockWorker }) => startMockWorker())
      .then(() => {
        if (active) setReady(true);
      })
      .catch(() => {
        if (active) setFailed(true);
      });

    return () => {
      active = false;
    };
  }, [mockEnabled]);

  if (failed) {
    return (
      <main className="provider-boot provider-boot-error" role="alert">
        <p className="eyebrow">前端独立预览</p>
        <h1>模拟数据没有启动</h1>
        <p>请刷新页面；如果仍然失败，请把浏览器截图发给开发者。</p>
      </main>
    );
  }

  if (!ready) {
    return (
      <main className="provider-boot" aria-busy="true" aria-live="polite">
        <span className="provider-boot-mark" aria-hidden="true">笨</span>
        <p>正在准备前端独立预览…</p>
      </main>
    );
  }

  return children;
}

export function AppProviders({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            refetchOnWindowFocus: false,
            retry: 1,
            staleTime: 15_000,
          },
          mutations: { retry: false },
        },
      }),
  );

  return (
    <MockGate>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </MockGate>
  );
}
