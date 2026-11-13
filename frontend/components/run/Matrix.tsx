import type { SourceIndex } from "@/components/run/Evidence";
import { CellBadge, SourceRef } from "@/components/ui";
import type { Claim, ResearchRequest } from "@/lib/api";
import { cellStatus, isConflict } from "@/lib/format";

export function Matrix({
  request,
  claims,
  index,
}: {
  request: ResearchRequest;
  claims: Claim[];
  index: SourceIndex;
}) {
  const attributes = request.attributes.length ? request.attributes : ["overview"];
  const regular = claims.filter((c) => !isConflict(c));

  return (
    <div className="overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
      <table className="w-full min-w-[40rem] border-collapse text-sm">
        <caption className="sr-only">
          Comparison of {request.entities.join(", ")} by {attributes.join(", ")}
        </caption>
        <thead className="bg-zinc-50 dark:bg-zinc-900">
          <tr>
            <th scope="col" className="px-3 py-2 text-left font-medium">
              Entity
            </th>
            {attributes.map((a) => (
              <th key={a} scope="col" className="px-3 py-2 text-left font-medium">
                {a}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {request.entities.map((entity) => (
            <tr key={entity} className="border-t border-zinc-200 dark:border-zinc-800">
              <th scope="row" className="px-3 py-2 text-left font-medium">
                {entity}
              </th>
              {attributes.map((attribute) => {
                const cell = regular.filter((c) => c.entity === entity && c.attribute === attribute);
                const status = cellStatus(cell);
                const shown =
                  status === "supported"
                    ? cell.filter((c) => c.verification_status === "supported")
                    : cell.filter((c) => c.spans.length > 0);
                const refIds = [...new Set(shown.flatMap((c) => c.source_record_ids))].filter((id) =>
                  index.numbers.has(id),
                );
                return (
                  <td key={attribute} className="px-3 py-2 align-top">
                    <CellBadge status={status} />
                    {refIds.map((id) => (
                      <SourceRef key={id} n={index.numbers.get(id)!} title={index.byId.get(id)?.title} />
                    ))}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
