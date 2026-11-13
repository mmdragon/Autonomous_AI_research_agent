"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Activity } from "@/components/run/Activity";
import { ClaimCard, ConflictCard, type SourceIndex } from "@/components/run/Evidence";
import { Matrix } from "@/components/run/Matrix";
import { Progress } from "@/components/run/Progress";
import { Report } from "@/components/run/Report";
import { Sources } from "@/components/run/Sources";
import { Card, Notice, RunStatusBadge, Section } from "@/components/ui";
import { api, ApiError, isActive, type RunDetail, type ToolCall } from "@/lib/api";
import { formatDateTime, isConflict, sourceNumbers } from "@/lib/format";

const POLL_MS = 1500;

const TOOL_LABEL = {
  wikipedia: "Wikipedia",
  hackernews: "Hacker News",
  user_url: "Your URL",
  document: "Your document",
} as const;

export function RunView() {
  const { id } = useParams<{ id: string }>();
  const [run, setRun] = useState<RunDetail | null>(null);
  const [calls, setCalls] = useState<ToolCall[]>([]);
  const [error, setError] = useState<{ message: string; notFound: boolean } | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      try {
        const [detail, toolCalls] = await Promise.all([
          api.getRun(id, controller.signal),
          api.toolCalls(id, controller.signal),
        ]);
        setRun(detail);
        setCalls(toolCalls);
        setError(null);
        if (isActive(detail.status)) timer.current = setTimeout(load, POLL_MS);
      } catch (err) {
        if (controller.signal.aborted) return;
        const status = err instanceof ApiError ? err.status : 0;
        setError({
          message: err instanceof ApiError ? err.message : "Couldn't load this run.",
          notFound: status === 404,
        });
        if (status !== 404) timer.current = setTimeout(load, POLL_MS * 4); // retry when back
      }
    };
    load();
    return () => {
      controller.abort();
      clearTimeout(timer.current);
    };
  }, [id, reloadKey]);

  const reload = useCallback(() => setReloadKey((k) => k + 1), []);

  const index: SourceIndex | null = useMemo(
    () => run && { byId: new Map(run.sources.map((s) => [s.id, s])), numbers: sourceNumbers(run.sources) },
    [run],
  );

  if (error?.notFound) {
    return (
      <Notice kind="error" title="Run not found">
        <Link href="/" className="underline">
          Back to all runs
        </Link>
      </Notice>
    );
  }
  if (!run || !index) {
    return error ? (
      <Notice kind="error">{error.message}</Notice>
    ) : (
      <p role="status" className="text-sm text-zinc-600">
        Loading run…
      </p>
    );
  }

  const conflicts = run.claims.filter(isConflict);
  const rest = run.claims.filter((c) => !isConflict(c));
  const findings = rest.filter((c) => c.verification_status === "supported");
  const unknowns = rest.filter((c) => c.verification_status === "unknown");
  const cited = new Set(run.claims.flatMap((c) => c.source_record_ids));
  const active = isActive(run.status);
  const done = run.status === "completed";

  const nav = [
    ["progress", "Progress"],
    ["plan", "Plan"],
    ...(run.request.entities.length ? [["matrix", "Comparison"]] : []),
    ["findings", `Findings (${findings.length})`],
    ["unknowns", `Unknowns (${unknowns.length})`],
    ["conflicts", `Conflicts (${conflicts.length})`],
    ["sources", `Sources (${run.sources.length})`],
    ...(run.has_report ? [["report", "Report"]] : []),
    ["activity", `Activity (${calls.length})`],
  ];

  return (
    <div className="space-y-8">
      <header className="space-y-2">
        <Link href="/" className="text-sm text-sky-700 underline-offset-2 hover:underline dark:text-sky-300">
          ← All runs
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold tracking-tight">{run.user_task}</h1>
          <RunStatusBadge status={run.status} />
        </div>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          Started {formatDateTime(run.created_at)}
          {run.completed_at && ` · finished ${formatDateTime(run.completed_at)}`}
        </p>
        <p className="sr-only" aria-live="polite">
          Run status: {run.status}
        </p>
        {error && <Notice kind="warning">Lost contact with the API; retrying. ({error.message})</Notice>}
      </header>

      <nav aria-label="Run sections" className="sticky top-[3.25rem] z-30 -mx-4 overflow-x-auto border-b border-zinc-200 bg-white/95 px-4 py-2 backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/95">
        <ul className="flex gap-4 whitespace-nowrap text-sm">
          {nav.map(([href, label]) => (
            <li key={href}>
              <a href={`#${href}`} className="text-zinc-700 hover:underline dark:text-zinc-300">
                {label}
              </a>
            </li>
          ))}
        </ul>
      </nav>

      <Section id="progress" title="Progress" description={active ? "Updating automatically…" : undefined}>
        <Progress run={run} onChanged={reload} />
      </Section>

      <Section id="plan" title="Plan" description="Research questions and the source queries the planner chose.">
        {run.plan ? (
          <div className="grid gap-4 md:grid-cols-2">
            <Card>
              <h3 className="mb-2 text-sm font-semibold">Questions ({run.plan.questions.length})</h3>
              <ol className="list-decimal space-y-1 pl-5 text-sm">
                {run.plan.questions.map((q) => (
                  <li key={q.id}>{q.text}</li>
                ))}
              </ol>
            </Card>
            <Card>
              <h3 className="mb-2 text-sm font-semibold">Source queries ({run.plan.queries.length})</h3>
              <ul className="space-y-1 text-sm">
                {run.plan.queries.map((q) => (
                  <li key={`${q.tool}:${q.query}`} className="flex gap-2">
                    <span className="w-28 shrink-0 text-zinc-600 dark:text-zinc-400">{TOOL_LABEL[q.tool]}</span>
                    <span className="break-all">
                      {q.tool === "document" ? `document ${q.query.slice(0, 8)}…` : q.query}
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
          </div>
        ) : (
          <p className="text-sm text-zinc-600">{active ? "Planning…" : "No plan was produced."}</p>
        )}
      </Section>

      {run.request.entities.length > 0 && (
        <Section
          id="matrix"
          title="Comparison"
          description="Supported needs a Wikipedia, URL or document source. Community only means just Hacker News discussion."
        >
          {run.claims.length ? (
            <Matrix request={run.request} claims={run.claims} index={index} />
          ) : (
            <p className="text-sm text-zinc-600">{active ? "Waiting for analysis…" : "No claims."}</p>
          )}
        </Section>
      )}

      <Section id="findings" title="Findings" description="Verbatim quotes verified against stored sources.">
        {findings.length ? (
          <ul className="space-y-2">
            {findings.map((c) => (
              <ClaimCard key={c.id} claim={c} index={index} />
            ))}
          </ul>
        ) : (
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            {active ? "Waiting for verification…" : "No claim could be verified against a non-community source."}
          </p>
        )}
      </Section>

      <Section
        id="unknowns"
        title="Unknowns and gaps"
        description="Not found in any source, or only mentioned in community discussion."
      >
        {unknowns.length ? (
          <ul className="space-y-2">
            {unknowns.map((c) => (
              <ClaimCard key={c.id} claim={c} index={index} />
            ))}
          </ul>
        ) : (
          <p className="text-sm text-zinc-600 dark:text-zinc-400">{active ? "Waiting…" : "None."}</p>
        )}
      </Section>

      <Section
        id="conflicts"
        title="Conflicts"
        description="Facts where different sources disagree: license model, founding year, initial release year, headquarters."
      >
        {conflicts.length ? (
          <ul className="space-y-3">
            {conflicts.map((c) => (
              <ConflictCard key={c.id} claim={c} index={index} />
            ))}
          </ul>
        ) : (
          <p className="text-sm text-zinc-600 dark:text-zinc-400">{active ? "Waiting…" : "None detected."}</p>
        )}
      </Section>

      <Section id="sources" title="Sources" description="Everything retrieved for this run, with retrieval dates.">
        {run.sources.length ? (
          <Sources sources={run.sources} cited={cited} />
        ) : (
          <p className="text-sm text-zinc-600 dark:text-zinc-400">{active ? "Researching…" : "No sources."}</p>
        )}
      </Section>

      {run.has_report && done && (
        <Section
          id="report"
          title="Report"
          description="Passed the evidence check before it was saved. Its [n] citations refer to the report's own source list, numbered in citation order."
        >
          <Report runId={run.id} sourceUrls={new Set(run.sources.map((s) => s.url))} />
        </Section>
      )}

      <Section id="activity" title="Activity log" description="Every source tool call, including failures.">
        <Activity calls={calls} />
      </Section>
    </div>
  );
}
