import { Badge, SourceKindBadge, SourceRef } from "@/components/ui";
import type { Claim, EvidenceSpan, Source } from "@/lib/api";
import { formatDate, VERIFICATION_LABEL } from "@/lib/format";

export type SourceIndex = { byId: Map<string, Source>; numbers: Map<string, number> };

export function Quote({ span, index }: { span: EvidenceSpan; index: SourceIndex }) {
  const source = index.byId.get(span.source_record_id);
  const n = index.numbers.get(span.source_record_id);
  return (
    <figure className="border-l-2 border-zinc-300 pl-3 dark:border-zinc-700">
      {/* Source text is rendered as plain text; React escapes it. */}
      <blockquote className="text-sm">“{span.quote}”</blockquote>
      {source && n && (
        <figcaption className="mt-1 flex flex-wrap items-center gap-2 text-xs text-zinc-600 dark:text-zinc-400">
          <SourceRef n={n} title={source.title} />
          <span className="truncate">{source.title}</span>
          <SourceKindBadge kind={source.source_kind} />
          {source.published_at && <span>posted {formatDate(source.published_at)}</span>}
        </figcaption>
      )}
    </figure>
  );
}

const STATUS_TONE = { supported: "green", contradicted: "red", unknown: "gray" } as const;

export function ClaimCard({ claim, index }: { claim: Claim; index: SourceIndex }) {
  const supports = claim.spans.filter((s) => s.stance === "supports");
  const stated = supports.find((s) => s.quote.includes(claim.claim_text));
  return (
    <li className="space-y-2 rounded-md border border-zinc-200 p-3 dark:border-zinc-800">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Badge color={STATUS_TONE[claim.verification_status]}>
          {VERIFICATION_LABEL[claim.verification_status]}
        </Badge>
        {claim.entity && <span className="font-medium">{claim.entity}</span>}
        {claim.attribute && <span className="text-zinc-600 dark:text-zinc-400">· {claim.attribute}</span>}
      </div>
      {stated ? (
        <Quote span={stated} index={index} />
      ) : (
        <p className="text-sm">{claim.spans.length ? `Unverified: ${claim.claim_text}` : claim.claim_text}</p>
      )}
      {claim.notes && <p className="text-xs text-zinc-600 dark:text-zinc-400">{claim.notes}</p>}
    </li>
  );
}

export function ConflictCard({ claim, index }: { claim: Claim; index: SourceIndex }) {
  const label =
    claim.verification_status === "contradicted"
      ? "Sources disagree"
      : claim.verification_status === "supported"
        ? "Supported; disputed in community discussion"
        : "Unverified; sources disagree";
  return (
    <li className="space-y-3 rounded-md border border-red-200 p-3 dark:border-red-900">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-semibold">
          {claim.entity}: {claim.attribute}
        </span>
        <Badge color={claim.verification_status === "contradicted" ? "red" : "amber"}>{label}</Badge>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <div>
          <p className="mb-1 text-xs font-medium uppercase tracking-wide text-zinc-500">Says</p>
          <div className="space-y-2">
            {claim.spans.filter((s) => s.stance === "supports").map((s) => (
              <Quote key={s.id} span={s} index={index} />
            ))}
          </div>
        </div>
        <div>
          <p className="mb-1 text-xs font-medium uppercase tracking-wide text-zinc-500">Disagrees</p>
          <div className="space-y-2">
            {claim.spans.filter((s) => s.stance === "contradicts").map((s) => (
              <Quote key={s.id} span={s} index={index} />
            ))}
          </div>
        </div>
      </div>
      {claim.notes && <p className="text-xs text-zinc-600 dark:text-zinc-400">{claim.notes}</p>}
    </li>
  );
}
