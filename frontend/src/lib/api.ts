// Server-side-only typed API client. BACKEND_URL and DASHBOARD_API_KEY are read from
// process.env here, inside functions that only ever run on the server (Server
// Components, Server Actions) -- neither value is ever sent to the browser bundle.
import "server-only";

export type {
  RepoListItem,
  RepoStatusResponse,
  RepoCreateResponse,
  AskResponse,
  AskDebugInfo,
  DebugChunkResponse,
  CitationResponse,
  ReviewResponse,
  FindingResponse,
  ReviewRunListItem,
  ReviewRunDetail,
  RepositoryStatus,
  ReviewRunStatus,
} from "./types";
import type {
  RepoListItem,
  RepoStatusResponse,
  RepoCreateResponse,
  AskResponse,
  ReviewResponse,
  ReviewRunListItem,
  ReviewRunDetail,
} from "./types";

export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, body: unknown, message?: string) {
    super(message ?? `Backend request failed with status ${status}`);
    this.status = status;
    this.body = body;
  }
}

function backendUrl(): string {
  return (process.env.BACKEND_URL ?? "http://localhost:8000").replace(
    /\/$/,
    "",
  );
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const apiKey = process.env.DASHBOARD_API_KEY;
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");
  if (init?.body) headers.set("Content-Type", "application/json");
  if (apiKey) headers.set("Authorization", `Bearer ${apiKey}`);

  const response = await fetch(`${backendUrl()}${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });

  if (!response.ok) {
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      // non-JSON error body; leave body as null
    }
    throw new ApiError(response.status, body);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function listRepos(): Promise<RepoListItem[]> {
  return request<RepoListItem[]>("/repos");
}

export function getRepository(id: string): Promise<RepoStatusResponse> {
  return request<RepoStatusResponse>(`/repos/${id}`);
}

export function createRepository(url: string): Promise<RepoCreateResponse> {
  return request<RepoCreateResponse>("/repos", {
    method: "POST",
    body: JSON.stringify({ url }),
  });
}

export function askRepository(
  id: string,
  question: string,
  debug: boolean,
): Promise<AskResponse> {
  const query = debug ? "?debug=true" : "";
  return request<AskResponse>(`/repos/${id}/ask${query}`, {
    method: "POST",
    body: JSON.stringify({ question }),
  });
}

export function reviewRepository(
  id: string,
  payload: { pr_url: string } | { diff: string },
): Promise<ReviewResponse> {
  return request<ReviewResponse>(`/repos/${id}/review`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listRepoReviews(
  repositoryId: string,
): Promise<ReviewRunListItem[]> {
  return request<ReviewRunListItem[]>(`/repos/${repositoryId}/reviews`);
}

export function getReviewRun(runId: string): Promise<ReviewRunDetail> {
  return request<ReviewRunDetail>(`/reviews/${runId}`);
}

export interface BenchmarkModeSummary {
  recall: number | null;
  false_positive_rate: number | null;
  evidence_validity_rate: number | null;
  avg_latency_seconds: number | null;
  avg_estimated_tokens: number | null;
  error_count: number;
  case_count: number;
  by_mutation_type: Record<
    string,
    {
      recall: number | null;
      false_positive_rate: number | null;
      case_count: number;
    }
  >;
}

export interface BenchmarkResults {
  rows: Record<string, unknown>[];
  summary: Record<string, BenchmarkModeSummary>;
  generated_at: string;
}

export async function getBenchmarkLatest(): Promise<BenchmarkResults | null> {
  try {
    return await request<BenchmarkResults>("/benchmark/latest");
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}
