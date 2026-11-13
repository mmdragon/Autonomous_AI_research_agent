import { SourceKindBadge } from "@/components/ui";
import type { Source } from "@/lib/api";
import { formatDate, formatDateTime } from "@/lib/format";

const isWeb = (url: string) => url.startsWith("https://") || url.startsWith("http://");

export function Sources({ sources, cited }: { sources: Source[]; cited: Set<string> }) {
  return (
    <ol className="space-y-2">
      {sources.map((s, i) => (
        <li
          key={s.id}
          id={`source-${i + 1}`}
          className="scroll-mt-28 rounded-md border border-zinc-200 p-3 target:ring-2 target:ring-sky-500 dark:border-zinc-800"
        >
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs text-zinc-500">[{i + 1}]</span>
            {isWeb(s.url) ? (
              <a
                href={s.url}
                target="_blank"
                rel="noopener noreferrer nofollow"
                className="font-medium text-sky-700 underline-offset-2 hover:underline dark:text-sky-300"
              >
                {s.title}
                <span className="sr-only"> (opens in a new tab)</span>
              </a>
            ) : (
              <span className="font-medium">{s.title}</span>
            )}
            <SourceKindBadge kind={s.source_kind} />
            {!cited.has(s.id) && <span className="text-xs text-zinc-500">not cited</span>}
          </div>
          <p className="mt-1 text-xs text-zinc-600 dark:text-zinc-400">
            {s.source_name} · retrieved {formatDateTime(s.retrieved_at)}
            {s.published_at && ` · posted ${formatDate(s.published_at)}`}
            {s.license && ` · ${s.license}`}
          </p>
          <details className="mt-1 text-sm">
            <summary className="cursor-pointer text-xs text-zinc-600 dark:text-zinc-400">Excerpt</summary>
            <p className="mt-1 whitespace-pre-line text-zinc-700 dark:text-zinc-300">{s.excerpt}</p>
            <p className="mt-1 break-all font-mono text-[11px] text-zinc-500">{s.url}</p>
          </details>
        </li>
      ))}
    </ol>
  );
}
