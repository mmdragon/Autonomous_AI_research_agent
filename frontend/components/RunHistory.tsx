"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Card, Notice, RunStatusBadge } from "@/components/ui";
import { api, ApiError, isActive, type RunSummary } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

const REFRESH_MS = 5000;

export function RunHistory() {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();
    const load = async () => {
      try {
        const list = await api.listRuns(controller.signal);
        setRuns(list);
        setError(null);
        if (list.some((r) => isActive(r.status))) timer = setTimeout(load, REFRESH_MS);
      } catch (err) {
        if (controller.signal.aborted) return;
        setError(err instanceof ApiError ? err.message : "Couldn't load run history.");
      }
    };
    load();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, []);

  return (
    <Card>
      <h2 className="mb-3 text-lg font-semibold tracking-tight">Run history</h2>
      {error && <Notice kind="error">{error}</Notice>}
      {!error && runs === null && (
        <p className="text-sm text-zinc-600 dark:text-zinc-400" role="status">
          Loading runs…
        </p>
      )}
      {runs?.length === 0 && (
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          No runs yet. Start one with the form, or use “Load example”.
        </p>
      )}
      {runs && runs.length > 0 && (
        <ul className="divide-y divide-zinc-200 dark:divide-zinc-800">
          {runs.map((run) => (
            <li key={run.id}>
              <Link
                href={`/runs/${run.id}`}
                className="flex flex-wrap items-center justify-between gap-2 py-2 hover:bg-zinc-50 focus-visible:outline-2 focus-visible:outline-sky-600 dark:hover:bg-zinc-800/50"
              >
                <span className="min-w-0">
                  <span className="block truncate font-medium">{run.user_task}</span>
                  <span className="block text-xs text-zinc-600 dark:text-zinc-400">
                    {formatDateTime(run.created_at)}
                    {run.error && ` · ${run.error}`}
                  </span>
                </span>
                <RunStatusBadge status={run.status} />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
