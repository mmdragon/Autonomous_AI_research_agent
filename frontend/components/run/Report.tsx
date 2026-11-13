"use client";

import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { buttonClass, Notice } from "@/components/ui";
import { api, ApiError, type Report as ReportData, reportDownloadUrl } from "@/lib/api";

/**
 * Renders the stored Markdown report. Only links that point at one of this run's stored
 * sources are clickable; any other link (e.g. one GFM autolinked) renders as plain text.
 */
export function Report({ runId, sourceUrls }: { runId: string; sourceUrls: Set<string> }) {
  const [report, setReport] = useState<ReportData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"rendered" | "markdown">("rendered");
  const [copied, setCopied] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    api
      .report(runId, controller.signal)
      .then(setReport)
      .catch((err) => {
        if (!controller.signal.aborted)
          setError(err instanceof ApiError ? err.message : "Couldn't load the report.");
      });
    return () => controller.abort();
  }, [runId]);

  async function copy() {
    if (!report) return;
    try {
      await navigator.clipboard.writeText(report.markdown);
      setCopied("Markdown copied to clipboard.");
    } catch {
      setCopied("Copy failed. Switch to the Markdown view and copy it manually.");
    }
  }

  if (error) return <Notice kind="error">{error}</Notice>;
  if (!report) return <p className="text-sm text-zinc-600" role="status">Loading report…</p>;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div role="group" aria-label="Report view" className="inline-flex rounded-md border border-zinc-300 dark:border-zinc-700">
          {(["rendered", "markdown"] as const).map((v) => (
            <button
              key={v}
              type="button"
              aria-pressed={view === v}
              onClick={() => setView(v)}
              className={`px-3 py-1.5 text-sm first:rounded-l-md last:rounded-r-md ${
                view === v ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900" : ""
              }`}
            >
              {v === "rendered" ? "Rendered" : "Markdown"}
            </button>
          ))}
        </div>
        <button type="button" className={buttonClass.secondary} onClick={copy}>
          Copy Markdown
        </button>
        <a className={buttonClass.secondary} href={reportDownloadUrl(runId)} download>
          Download .md
        </a>
        <p className="text-sm text-zinc-600 dark:text-zinc-400" role="status" aria-live="polite">
          {copied}
        </p>
      </div>
      {view === "rendered" ? (
        <article className="report max-w-none overflow-x-auto rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
          {/* Raw HTML in the Markdown is never rendered, and images are dropped. */}
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            skipHtml
            disallowedElements={["img"]}
            components={{
              a: ({ href, children }) =>
                href && sourceUrls.has(href) ? (
                  <a href={href} target="_blank" rel="noopener noreferrer nofollow">
                    {children}
                  </a>
                ) : (
                  <span>{children}</span>
                ),
            }}
          >
            {report.markdown}
          </ReactMarkdown>
        </article>
      ) : (
        <pre className="max-h-[40rem] overflow-auto rounded-lg border border-zinc-200 bg-zinc-50 p-4 text-xs whitespace-pre-wrap dark:border-zinc-800 dark:bg-zinc-900">
          {report.markdown}
        </pre>
      )}
    </div>
  );
}
