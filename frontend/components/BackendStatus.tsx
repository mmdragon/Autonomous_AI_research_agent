"use client";

import { useEffect, useState } from "react";

import { API_BASE_URL, getHealth, type Health } from "@/lib/api";

type State =
  | { kind: "loading" }
  | { kind: "ok"; health: Health }
  | { kind: "error"; message: string };

export function BackendStatus() {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    getHealth(controller.signal)
      .then((health) => setState({ kind: "ok", health }))
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setState({ kind: "error", message: err instanceof Error ? err.message : String(err) });
      });
    return () => controller.abort();
  }, []);

  return (
    <section
      aria-live="polite"
      aria-busy={state.kind === "loading"}
      className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800"
    >
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-zinc-500">
        Backend status
      </h2>
      {state.kind === "loading" && <p>Checking {API_BASE_URL}…</p>}
      {state.kind === "error" && (
        <p role="alert" className="text-red-700 dark:text-red-400">
          Can&apos;t reach the API at {API_BASE_URL}. Start the backend and reload. ({state.message})
        </p>
      )}
      {state.kind === "ok" && (
        <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
          <dt className="text-zinc-500">API</dt>
          <dd>{state.health.status}</dd>
          <dt className="text-zinc-500">Database</dt>
          <dd>{state.health.database}</dd>
          <dt className="text-zinc-500">LLM provider</dt>
          <dd>{state.health.llm_provider}</dd>
          <dt className="text-zinc-500">Sources</dt>
          <dd>{state.health.sources_mode}</dd>
        </dl>
      )}
    </section>
  );
}
