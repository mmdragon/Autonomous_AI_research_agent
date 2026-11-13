import { Badge } from "@/components/ui";
import type { ToolCall } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

const TONE = { ok: "green", error: "red", blocked: "amber" } as const;

export function Activity({ calls }: { calls: ToolCall[] }) {
  if (!calls.length) {
    return <p className="text-sm text-zinc-600 dark:text-zinc-400">No tool calls yet.</p>;
  }
  return (
    <div className="overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
      <table className="w-full min-w-[44rem] text-sm">
        <caption className="sr-only">Tool calls made during this run</caption>
        <thead className="bg-zinc-50 text-left dark:bg-zinc-900">
          <tr>
            <th scope="col" className="px-3 py-2 font-medium">Tool</th>
            <th scope="col" className="px-3 py-2 font-medium">Request</th>
            <th scope="col" className="px-3 py-2 font-medium">Status</th>
            <th scope="col" className="px-3 py-2 text-right font-medium">Results</th>
            <th scope="col" className="px-3 py-2 text-right font-medium">HTTP</th>
            <th scope="col" className="px-3 py-2 text-right font-medium">ms</th>
            <th scope="col" className="px-3 py-2 font-medium">Started</th>
          </tr>
        </thead>
        <tbody>
          {calls.map((c) => (
            <tr key={c.id} className="border-t border-zinc-200 align-top dark:border-zinc-800">
              <td className="px-3 py-2 font-mono text-xs">{c.tool}</td>
              <td className="max-w-[20rem] px-3 py-2">
                <span className="break-all">{c.request}</span>
                {c.error && <p className="mt-1 text-xs text-red-700 dark:text-red-400">{c.error}</p>}
              </td>
              <td className="px-3 py-2">
                <Badge color={TONE[c.status]}>{c.status}</Badge>
              </td>
              <td className="px-3 py-2 text-right tabular-nums">{c.result_count ?? "—"}</td>
              <td className="px-3 py-2 text-right tabular-nums">{c.http_requests}</td>
              <td className="px-3 py-2 text-right tabular-nums">{c.duration_ms ?? "—"}</td>
              <td className="px-3 py-2 text-xs text-zinc-600 dark:text-zinc-400">{formatDateTime(c.started_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
