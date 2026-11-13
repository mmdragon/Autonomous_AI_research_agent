"use client";

import { useEffect, useState } from "react";

import { api, type Health } from "@/lib/api";

type State = { kind: "loading" } | { kind: "ok"; health: Health } | { kind: "error" };

/** Compact header indicator: API reachable, and whether sources are offline fixtures. */
export function BackendStatus() {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    api
      .health(controller.signal)
      .then((health) => setState({ kind: "ok", health }))
      .catch(() => {
        if (!controller.signal.aborted) setState({ kind: "error" });
      });
    return () => controller.abort();
  }, []);

  if (state.kind === "loading") {
    return <p className="text-xs text-zinc-500" aria-live="polite">Checking API…</p>;
  }
  if (state.kind === "error") {
    return (
      <p role="alert" className="text-xs font-medium text-red-700 dark:text-red-400">
        API unreachable — start the backend
      </p>
    );
  }
  const { health } = state;
  const offline = health.sources_mode === "fixtures";
  return (
    <p className="flex items-center gap-2 text-xs text-zinc-600 dark:text-zinc-400" aria-live="polite">
      <span
        aria-hidden
        className={`h-2 w-2 rounded-full ${health.database === "ok" ? "bg-emerald-500" : "bg-red-500"}`}
      />
      <span>
        {offline ? "Offline" : "Live"}
        <span className="hidden sm:inline">
          {offline ? " (recorded sources)" : " sources"} · analysis: {health.llm_provider}
        </span>
        {health.database !== "ok" && " · database unavailable"}
      </span>
    </p>
  );
}
