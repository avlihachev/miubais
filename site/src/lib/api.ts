const BASE = "http://127.0.0.1:8787";
const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);

export function isLocalHost(hostname: string): boolean {
  return LOCAL_HOSTS.has(hostname);
}

export class ApiUnavailable extends Error {
  constructor() {
    super("local API not running");
  }
}

export type Status = "passed" | "failed" | "skipped";
export type Progress = Record<string, Record<string, { status: Status; at: string; output_path: string | null }>>;
export type ApiError = { status: number; detail: string };
export type Hint = { text: string; source: string; leaks_rejected: number };

async function request(path: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(BASE + path, init);
  } catch (err) {
    if (err instanceof TypeError) throw new ApiUnavailable();
    throw err;
  }
}

async function errorOf(res: Response): Promise<ApiError> {
  const body = await res.json().catch(() => ({}));
  return { status: res.status, detail: body.detail ?? res.statusText };
}

export async function getProgress(): Promise<Progress | ApiError> {
  const res = await request("/progress");
  if (!res.ok) return errorOf(res);
  return (await res.json()).exercises;
}

export async function getFreshness(): Promise<unknown | ApiError> {
  const res = await request("/freshness");
  return res.ok ? res.json() : errorOf(res);
}

export async function getHint(id: string): Promise<Hint | ApiError> {
  const res = await request(`/hint/${id}`, { method: "POST" });
  return res.ok ? res.json() : errorOf(res);
}

export async function runCheck(
  id: string,
  onEvent: (name: string, data: any) => void,
): Promise<ApiError | null> {
  const res = await request(`/check/${id}`, { method: "POST" });
  if (!res.ok || !res.body) return errorOf(res);
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) return null;
    buffer += value;
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";
    for (const block of blocks) {
      const name = /^event: (.*)$/m.exec(block)?.[1];
      const data = /^data: (.*)$/m.exec(block)?.[1];
      if (name && data) onEvent(name, JSON.parse(data));
    }
  }
}

export function isApiError(value: unknown): value is ApiError {
  return typeof value === "object" && value !== null && "detail" in value && "status" in value;
}
