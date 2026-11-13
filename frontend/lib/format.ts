import type { Claim, RunStatus, Source, SourceKind, VerificationStatus } from "@/lib/api";

export function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, { dateStyle: "medium" });
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export const RUN_STATUS_LABEL: Record<RunStatus, string> = {
  pending: "Queued",
  running: "Running",
  completed: "Completed",
  failed: "Failed",
};

export const SOURCE_KIND_LABEL: Record<SourceKind, string> = {
  reference: "Reference",
  community: "Community",
  user_url: "Your URL",
  document: "Your document",
};

export const VERIFICATION_LABEL: Record<VerificationStatus, string> = {
  supported: "Supported",
  contradicted: "Contradicted",
  unknown: "Unknown",
};

/** Claims with a contradicting span are shown only under Conflicts (as in the report). */
export const isConflict = (c: Claim) => c.spans.some((s) => s.stance === "contradicts");

/** Stable [n] numbering for sources, in the order the API lists them. */
export function sourceNumbers(sources: Source[]): Map<string, number> {
  return new Map(sources.map((s, i) => [s.id, i + 1]));
}

export type CellStatus = "supported" | "conflicting" | "community" | "unknown";

export const CELL_LABEL: Record<CellStatus, string> = {
  supported: "Supported",
  conflicting: "Conflicting",
  community: "Community only",
  unknown: "Unknown",
};

/** Same rules as the report's comparison matrix (backend MockWriter._cell). */
export function cellStatus(claims: Claim[]): CellStatus {
  if (claims.some((c) => c.verification_status === "supported")) return "supported";
  if (claims.some((c) => c.verification_status === "contradicted")) return "conflicting";
  if (claims.some((c) => c.spans.length > 0)) return "community";
  return "unknown";
}

/** Split a textarea into trimmed, non-empty, case-insensitively unique lines. */
export function parseList(text: string, separators = /[\n,]/): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of text.split(separators)) {
    const value = raw.trim();
    if (value && !seen.has(value.toLowerCase())) {
      seen.add(value.toLowerCase());
      out.push(value);
    }
  }
  return out;
}
