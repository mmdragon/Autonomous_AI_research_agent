"use client";

import { useState } from "react";

import { Badge, buttonClass, Notice } from "@/components/ui";
import { api, ApiError, type RunDetail, type Stage, STAGES, type Step } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

const STAGE_LABEL: Record<Stage, string> = {
  plan: "Plan",
  research: "Research",
  analyze: "Analyze",
  verify: "Verify",
  write: "Write report",
};

type StageState = "done" | "running" | "failed" | "waiting";

function stageState(steps: Step[], stage: Stage): { state: StageState; step?: Step; attempts: number } {
  const attempts = steps.filter((s) => s.stage === stage);
  const last = attempts.at(-1);
  if (!last) return { state: "waiting", attempts: 0 };
  const state = last.status === "completed" ? "done" : last.status === "running" ? "running" : "failed";
  return { state, step: last, attempts: attempts.length };
}

const MARK: Record<StageState, { symbol: string; className: string; label: string }> = {
  done: { symbol: "✓", className: "bg-emerald-600 text-white", label: "completed" },
  running: { symbol: "…", className: "bg-sky-600 text-white animate-pulse", label: "running" },
  failed: { symbol: "!", className: "bg-red-600 text-white", label: "failed" },
  waiting: { symbol: "", className: "border border-zinc-300 dark:border-zinc-700", label: "not started" },
};

export function Progress({ run, onChanged }: { run: RunDetail; onChanged: () => void }) {
  const [resuming, setResuming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function resume() {
    setResuming(true);
    setError(null);
    try {
      await api.resumeRun(run.id);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't resume the run.");
    } finally {
      setResuming(false);
    }
  }

  return (
    <div className="space-y-3">
      <ol className="grid gap-2 sm:grid-cols-5" aria-label="Workflow stages">
        {STAGES.map((stage) => {
          const { state, step, attempts } = stageState(run.steps, stage);
          const mark = MARK[state];
          return (
            <li key={stage} className="rounded-md border border-zinc-200 p-3 dark:border-zinc-800">
              <div className="flex items-center gap-2">
                <span
                  aria-hidden
                  className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold ${mark.className}`}
                >
                  {mark.symbol}
                </span>
                <span className="font-medium">{STAGE_LABEL[stage]}</span>
                <span className="sr-only">: {mark.label}</span>
                {attempts > 1 && <Badge>{attempts} attempts</Badge>}
              </div>
              {step?.output_summary && (
                <p className="mt-2 text-xs text-zinc-600 dark:text-zinc-400">{step.output_summary}</p>
              )}
              {state === "failed" && step?.error && (
                <p className="mt-2 text-xs text-red-700 dark:text-red-400">{step.error}</p>
              )}
              {step?.completed_at && (
                <p className="mt-1 text-[11px] text-zinc-500">{formatDateTime(step.completed_at)}</p>
              )}
            </li>
          );
        })}
      </ol>
      {run.status === "failed" && (
        <Notice kind="error" title="This run stopped">
          <p>{run.error}</p>
          <p className="mt-1">
            Resume continues from the stage that failed; completed stages are not repeated.
          </p>
          <button type="button" className={`${buttonClass.secondary} mt-2`} onClick={resume} disabled={resuming}>
            {resuming ? "Resuming…" : "Resume run"}
          </button>
          {error && <p className="mt-2 font-medium">{error}</p>}
        </Notice>
      )}
    </div>
  );
}
