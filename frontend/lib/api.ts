// Typed client for the FastAPI backend. Types mirror backend/app/schemas/research.py.

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// Limits mirror ResearchRequest validation on the backend.
export const LIMITS = {
  entities: 8,
  attributes: 6,
  questions: 5,
  userUrls: 5,
  documents: 5,
  maxSources: 25,
  uploadBytes: 1024 * 1024,
} as const;
export const DOCUMENT_EXTENSIONS = [".txt", ".md", ".markdown"];

export type Health = {
  status: "ok";
  database: "ok" | "unavailable";
  llm_provider: "mock";
  sources_mode: "fixtures" | "live";
};

export type Stage = "plan" | "research" | "analyze" | "verify" | "write";
export const STAGES: Stage[] = ["plan", "research", "analyze", "verify", "write"];
export type RunStatus = "pending" | "running" | "completed" | "failed";
export type StepStatus = "running" | "completed" | "failed";
export type VerificationStatus = "supported" | "contradicted" | "unknown";
export type SourceKind = "reference" | "community" | "user_url" | "document";

export type ResearchRequest = {
  topic: string;
  questions: string[];
  entities: string[];
  attributes: string[];
  user_urls: string[];
  document_ids: string[];
  max_sources: number;
  output_format: "markdown";
};

export type ToolQuery = { tool: "wikipedia" | "hackernews" | "user_url" | "document"; query: string };
export type ResearchQuestion = {
  id: string;
  text: string;
  entity: string | null;
  attribute: string | null;
};
export type ResearchPlan = { questions: ResearchQuestion[]; queries: ToolQuery[] };

export type Step = {
  id: string;
  stage: Stage;
  status: StepStatus;
  input_summary: string | null;
  output_summary: string | null;
  error: string | null;
  started_at: string | null;
  completed_at: string | null;
};

export type Source = {
  id: string;
  url: string;
  title: string;
  source_name: string;
  source_kind: SourceKind;
  retrieved_at: string;
  published_at: string | null;
  excerpt: string;
  content_hash: string;
  license: string | null;
};

export type EvidenceSpan = {
  id: string;
  source_record_id: string;
  quote: string;
  start: number;
  end: number;
  stance: "supports" | "contradicts";
};

export type Claim = {
  id: string;
  entity: string | null;
  attribute: string | null;
  claim_text: string;
  claim_type: "fact" | "analysis";
  verification_status: VerificationStatus;
  notes: string | null;
  spans: EvidenceSpan[];
  source_record_ids: string[];
};

export type RunSummary = {
  id: string;
  user_task: string;
  status: RunStatus;
  error: string | null;
  created_at: string;
  completed_at: string | null;
};

export type RunDetail = RunSummary & {
  request: ResearchRequest;
  plan: ResearchPlan | null;
  steps: Step[];
  sources: Source[];
  claims: Claim[];
  has_report: boolean;
};

export type ToolCall = {
  id: string;
  step_id: string | null;
  tool: string;
  request: string;
  status: "ok" | "error" | "blocked";
  result_count: number | null;
  error: string | null;
  http_requests: number;
  started_at: string;
  duration_ms: number | null;
};

export type Report = { id: string; run_id: string; markdown: string; created_at: string };

export type UploadedDocument = {
  id: string;
  filename: string;
  size_bytes: number;
  content_hash: string;
  excerpt: string;
  created_at: string;
};

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

type ValidationItem = { loc?: (string | number)[]; msg?: string };

/** Turn FastAPI error bodies (string detail or 422 item list) into one readable message. */
function describeError(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return (detail as ValidationItem[])
      .map((d) => {
        const field = (d.loc ?? []).filter((p) => p !== "body").join(" → ");
        return field ? `${field}: ${d.msg ?? "invalid"}` : (d.msg ?? "invalid");
      })
      .join("; ");
  }
  return `Request failed (HTTP ${status})`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, { cache: "no-store", ...init });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(`Can't reach the API at ${API_BASE_URL}. Is the backend running?`, 0);
  }
  const body = res.headers.get("content-type")?.includes("json") ? await res.json() : null;
  if (!res.ok) throw new ApiError(describeError(res.status, body), res.status);
  return body as T;
}

const json = (data: unknown): RequestInit => ({
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify(data),
});

export const api = {
  health: (signal?: AbortSignal) => request<Health>("/api/health", { signal }),
  listRuns: (signal?: AbortSignal) => request<RunSummary[]>("/api/runs", { signal }),
  getRun: (id: string, signal?: AbortSignal) =>
    request<RunDetail>(`/api/runs/${encodeURIComponent(id)}`, { signal }),
  toolCalls: (id: string, signal?: AbortSignal) =>
    request<ToolCall[]>(`/api/runs/${encodeURIComponent(id)}/tool-calls`, { signal }),
  report: (id: string, signal?: AbortSignal) =>
    request<Report>(`/api/runs/${encodeURIComponent(id)}/report`, { signal }),
  createRun: (body: ResearchRequest) => request<RunDetail>("/api/runs", json(body)),
  resumeRun: (id: string) =>
    request<RunDetail>(`/api/runs/${encodeURIComponent(id)}/resume`, { method: "POST" }),
  uploadDocument: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<UploadedDocument>("/api/documents", { method: "POST", body: form });
  },
};

export const reportDownloadUrl = (id: string) =>
  `${API_BASE_URL}/api/runs/${encodeURIComponent(id)}/report.md`;

export const isActive = (status: RunStatus) => status === "pending" || status === "running";
