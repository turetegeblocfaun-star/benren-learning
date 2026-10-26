import type { ZodType } from "zod";

export class AppError extends Error {
  constructor(
    public code: string,
    message: string,
    public requestId?: string,
    public status?: number,
  ) {
    super(message);
    this.name = "AppError";
  }
}

export async function apiFetchContract<T>(schema: ZodType<T>, path: string, init: RequestInit = {}): Promise<T> {
  const value = await apiFetch<unknown>(path, init);
  const result = schema.safeParse(value);
  if (!result.success) {
    throw new AppError("CONTRACT_MISMATCH", "服务返回的数据格式发生变化，请刷新后重试。");
  }
  return result.data;
}

type ErrorEnvelope = {
  error?: { code?: string; message?: string; request_id?: string };
};

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers,
      credentials: "include",
      cache: "no-store",
    });
  } catch {
    throw new AppError("NETWORK_ERROR", "网络连接失败，请检查网络后重试。");
  }
  if (!response.ok) {
    let envelope: ErrorEnvelope = {};
    try {
      envelope = (await response.json()) as ErrorEnvelope;
    } catch {
      // Non-JSON proxy errors use the safe fallback below.
    }
    throw new AppError(
      envelope.error?.code ?? "HTTP_ERROR",
      envelope.error?.message ?? "请求没有成功，请稍后重试。",
      envelope.error?.request_id,
      response.status,
    );
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function jsonBody(value: unknown): string {
  return JSON.stringify(value);
}

export function idempotencyKey(prefix: string): string {
  const random = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
  return `${prefix}-${random}`;
}

export function presentError(error: unknown): { message: string; detail?: string } {
  if (error instanceof AppError) {
    return {
      message: error.message,
      detail: error.requestId ? `问题编号：${error.requestId}` : undefined,
    };
  }
  return { message: "发生了未预期的问题，请刷新后重试。" };
}
