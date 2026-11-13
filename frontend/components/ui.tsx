import type { ReactNode } from "react";

import type { RunStatus, SourceKind } from "@/lib/api";
import { CELL_LABEL, type CellStatus, RUN_STATUS_LABEL, SOURCE_KIND_LABEL } from "@/lib/format";

const tone = {
  green: "bg-emerald-100 text-emerald-900 ring-emerald-300 dark:bg-emerald-950 dark:text-emerald-200 dark:ring-emerald-800",
  red: "bg-red-100 text-red-900 ring-red-300 dark:bg-red-950 dark:text-red-200 dark:ring-red-800",
  amber: "bg-amber-100 text-amber-900 ring-amber-300 dark:bg-amber-950 dark:text-amber-200 dark:ring-amber-800",
  blue: "bg-sky-100 text-sky-900 ring-sky-300 dark:bg-sky-950 dark:text-sky-200 dark:ring-sky-800",
  gray: "bg-zinc-100 text-zinc-800 ring-zinc-300 dark:bg-zinc-800 dark:text-zinc-200 dark:ring-zinc-700",
  violet: "bg-violet-100 text-violet-900 ring-violet-300 dark:bg-violet-950 dark:text-violet-200 dark:ring-violet-800",
} as const;
type Tone = keyof typeof tone;

export function Badge({ children, color = "gray" }: { children: ReactNode; color?: Tone }) {
  return (
    <span
      className={`inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${tone[color]}`}
    >
      {children}
    </span>
  );
}

const RUN_TONE: Record<RunStatus, Tone> = {
  pending: "gray",
  running: "blue",
  completed: "green",
  failed: "red",
};

export function RunStatusBadge({ status }: { status: RunStatus }) {
  return <Badge color={RUN_TONE[status]}>{RUN_STATUS_LABEL[status]}</Badge>;
}

const KIND_TONE: Record<SourceKind, Tone> = {
  reference: "blue",
  community: "amber",
  user_url: "violet",
  document: "violet",
};

export function SourceKindBadge({ kind }: { kind: SourceKind }) {
  return <Badge color={KIND_TONE[kind]}>{SOURCE_KIND_LABEL[kind]}</Badge>;
}

const CELL_TONE: Record<CellStatus, Tone> = {
  supported: "green",
  conflicting: "red",
  community: "amber",
  unknown: "gray",
};

export function CellBadge({ status }: { status: CellStatus }) {
  return <Badge color={CELL_TONE[status]}>{CELL_LABEL[status]}</Badge>;
}

export function Notice({
  kind = "info",
  title,
  children,
}: {
  kind?: "info" | "error" | "warning";
  title?: string;
  children: ReactNode;
}) {
  const styles = {
    info: "border-sky-300 bg-sky-50 text-sky-950 dark:border-sky-800 dark:bg-sky-950/40 dark:text-sky-100",
    warning:
      "border-amber-300 bg-amber-50 text-amber-950 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-100",
    error: "border-red-300 bg-red-50 text-red-950 dark:border-red-800 dark:bg-red-950/40 dark:text-red-100",
  }[kind];
  return (
    <div role={kind === "error" ? "alert" : "status"} className={`rounded-md border p-3 text-sm ${styles}`}>
      {title && <p className="font-semibold">{title}</p>}
      <div className={title ? "mt-1" : undefined}>{children}</div>
    </div>
  );
}

/** Citation chip linking to the source in the Sources section. */
export function SourceRef({ n, title }: { n: number; title?: string }) {
  return (
    <a
      href={`#source-${n}`}
      className="ml-1 rounded px-1 font-mono text-xs text-sky-700 underline-offset-2 hover:underline focus-visible:outline-2 dark:text-sky-300"
      aria-label={`Source ${n}${title ? `: ${title}` : ""}`}
    >
      [{n}]
    </a>
  );
}

export function Section({
  id,
  title,
  description,
  children,
  actions,
}: {
  id: string;
  title: string;
  description?: ReactNode;
  children: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="scroll-mt-28">
      <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 id={`${id}-title`} className="text-lg font-semibold tracking-tight">
            {title}
          </h2>
          {description && <p className="text-sm text-zinc-600 dark:text-zinc-400">{description}</p>}
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900 ${className}`}>
      {children}
    </div>
  );
}

export const buttonClass = {
  primary:
    "inline-flex items-center justify-center rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-600 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300",
  secondary:
    "inline-flex items-center justify-center rounded-md border border-zinc-300 bg-white px-3 py-1.5 text-sm font-medium hover:bg-zinc-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-600 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-900 dark:hover:bg-zinc-800",
};
