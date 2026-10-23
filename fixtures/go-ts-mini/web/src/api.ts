import type { JobStatus } from "./status.ts";

export interface Job {
  id: string;
  reference: string;
  source_lang: string;
  target_lang: string;
  hours_estimate: number;
  translator?: string;
  status: JobStatus;
  due_at?: string;
  created_at: string;
}

export interface ApiErrorBody {
  error: { code: string; message: string };
}

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(status: number, body: ApiErrorBody) {
    super(body.error.message);
    this.code = body.error.code;
    this.status = status;
  }
}

export class JobsClient {
  readonly baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
  }

  async list(status?: JobStatus): Promise<Job[]> {
    const query = status ? `?status=${encodeURIComponent(status)}` : "";
    const body = await this.request<{ jobs: Job[] }>("GET", `/jobs${query}`);
    return body.jobs;
  }

  async get(id: string): Promise<Job> {
    return this.request<Job>("GET", `/jobs/${encodeURIComponent(id)}`);
  }

  async cancel(id: string): Promise<Job> {
    return this.request<Job>("POST", `/jobs/${encodeURIComponent(id)}/cancel`);
  }

  private async request<T>(method: string, path: string): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      method,
      headers: { Accept: "application/json" },
    });
    const body: unknown = await response.json();
    if (!response.ok) {
      throw new ApiError(response.status, body as ApiErrorBody);
    }
    return body as T;
  }
}
