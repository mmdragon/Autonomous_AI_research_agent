"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useId, useRef, useState } from "react";

import { buttonClass, Card, Notice } from "@/components/ui";
import { api, ApiError, DOCUMENT_EXTENSIONS, LIMITS, type ResearchRequest } from "@/lib/api";
import { formatBytes, parseList } from "@/lib/format";

const EXAMPLE = {
  topic: "headless CMS",
  entities: "Strapi\nContentful\nSanity CMS\nDirectus\nPayload CMS",
  attributes: "content modeling\nAPI options\nintegrations\ndeveloper experience\npricing",
  questions: "",
  urls: "",
  maxSources: 15,
};

type Fields = typeof EXAMPLE;
const EMPTY: Fields = { topic: "", entities: "", attributes: "", questions: "", urls: "", maxSources: 15 };

function validate(f: Fields, files: File[]): { request?: Omit<ResearchRequest, "document_ids">; errors: string[] } {
  const errors: string[] = [];
  const topic = f.topic.trim();
  if (topic.length < 3) errors.push("Topic must be at least 3 characters.");
  if (topic.length > 300) errors.push("Topic must be at most 300 characters.");
  const entities = parseList(f.entities);
  const attributes = parseList(f.attributes);
  const questions = parseList(f.questions, /\n/);
  const urls = parseList(f.urls, /\s+/);
  if (entities.length > LIMITS.entities) errors.push(`At most ${LIMITS.entities} entities.`);
  if (attributes.length > LIMITS.attributes) errors.push(`At most ${LIMITS.attributes} attributes.`);
  if (questions.length > LIMITS.questions) errors.push(`At most ${LIMITS.questions} questions.`);
  if (urls.length > LIMITS.userUrls) errors.push(`At most ${LIMITS.userUrls} URLs.`);
  for (const url of urls) {
    try {
      const parsed = new URL(url);
      if (parsed.protocol !== "http:" && parsed.protocol !== "https:") throw new Error();
    } catch {
      errors.push(`Not an http(s) URL: ${url}`);
    }
  }
  if (files.length > LIMITS.documents) errors.push(`At most ${LIMITS.documents} documents.`);
  for (const file of files) {
    const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
    if (!DOCUMENT_EXTENSIONS.includes(ext)) errors.push(`${file.name}: only .txt and .md files.`);
    if (file.size > LIMITS.uploadBytes) errors.push(`${file.name}: larger than ${formatBytes(LIMITS.uploadBytes)}.`);
  }
  if (!Number.isInteger(f.maxSources) || f.maxSources < 1 || f.maxSources > LIMITS.maxSources) {
    errors.push(`Number of sources must be between 1 and ${LIMITS.maxSources}.`);
  }
  if (errors.length) return { errors };
  return {
    errors,
    request: {
      topic,
      entities,
      attributes,
      questions,
      user_urls: urls,
      max_sources: f.maxSources,
      output_format: "markdown",
    },
  };
}

const inputClass =
  "mt-1 block w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-sky-600 focus:outline-none focus:ring-2 focus:ring-sky-600/30 dark:border-zinc-700 dark:bg-zinc-950";
const labelClass = "block text-sm font-medium";
const hintClass = "mt-1 text-xs text-zinc-600 dark:text-zinc-400";

export function ResearchForm() {
  const router = useRouter();
  const id = useId();
  const [fields, setFields] = useState<Fields>(EMPTY);
  const [files, setFiles] = useState<File[]>([]);
  const [errors, setErrors] = useState<string[]>([]);
  const [progress, setProgress] = useState<string | null>(null);
  const errorRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const set = <K extends keyof Fields>(key: K, value: Fields[K]) =>
    setFields((f) => ({ ...f, [key]: value }));

  function showErrors(list: string[]) {
    setErrors(list);
    requestAnimationFrame(() => errorRef.current?.focus());
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const { request, errors: problems } = validate(fields, files);
    if (!request) return showErrors(problems);
    setErrors([]);
    try {
      const documentIds: string[] = [];
      for (const [i, file] of files.entries()) {
        setProgress(`Uploading ${file.name} (${i + 1} of ${files.length})…`);
        documentIds.push((await api.uploadDocument(file)).id);
      }
      setProgress("Starting research run…");
      const run = await api.createRun({ ...request, document_ids: documentIds });
      router.push(`/runs/${run.id}`);
    } catch (err) {
      setProgress(null);
      showErrors([err instanceof ApiError ? err.message : "Something went wrong starting the run."]);
    }
  }

  const busy = progress !== null;
  return (
    <Card>
      <form onSubmit={onSubmit} noValidate aria-describedby={`${id}-intro`} className="space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <h2 className="text-lg font-semibold tracking-tight">New research task</h2>
            <p id={`${id}-intro`} className="text-sm text-zinc-600 dark:text-zinc-400">
              Entities and attributes build the comparison matrix. Sources are read-only:
              Wikipedia, Hacker News, plus any URLs or documents you add.
            </p>
          </div>
          <button
            type="button"
            className={buttonClass.secondary}
            onClick={() => {
              setFields(EXAMPLE);
              setErrors([]);
            }}
            disabled={busy}
          >
            Load example
          </button>
        </div>

        {errors.length > 0 && (
          <div ref={errorRef} tabIndex={-1} className="outline-none">
            <Notice kind="error" title="Please fix the following">
              <ul className="list-disc pl-5">
                {errors.map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ul>
            </Notice>
          </div>
        )}

        <div>
          <label htmlFor={`${id}-topic`} className={labelClass}>
            Topic <span className="text-red-700 dark:text-red-400" aria-hidden>*</span>
          </label>
          <input
            id={`${id}-topic`}
            className={inputClass}
            value={fields.topic}
            onChange={(e) => set("topic", e.target.value)}
            required
            minLength={3}
            maxLength={300}
            placeholder="e.g. headless CMS"
            disabled={busy}
          />
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <label htmlFor={`${id}-entities`} className={labelClass}>
              Entities to compare
            </label>
            <textarea
              id={`${id}-entities`}
              className={inputClass}
              rows={5}
              value={fields.entities}
              onChange={(e) => set("entities", e.target.value)}
              aria-describedby={`${id}-entities-hint`}
              disabled={busy}
            />
            <p id={`${id}-entities-hint`} className={hintClass}>
              One per line or comma-separated, up to {LIMITS.entities}.
            </p>
          </div>
          <div>
            <label htmlFor={`${id}-attributes`} className={labelClass}>
              Attributes
            </label>
            <textarea
              id={`${id}-attributes`}
              className={inputClass}
              rows={5}
              value={fields.attributes}
              onChange={(e) => set("attributes", e.target.value)}
              aria-describedby={`${id}-attributes-hint`}
              disabled={busy}
            />
            <p id={`${id}-attributes-hint`} className={hintClass}>
              Matrix columns, up to {LIMITS.attributes}. Leave empty for an overview.
            </p>
          </div>
        </div>

        <div>
          <label htmlFor={`${id}-questions`} className={labelClass}>
            Other questions
          </label>
          <textarea
            id={`${id}-questions`}
            className={inputClass}
            rows={2}
            value={fields.questions}
            onChange={(e) => set("questions", e.target.value)}
            aria-describedby={`${id}-questions-hint`}
            disabled={busy}
          />
          <p id={`${id}-questions-hint`} className={hintClass}>
            One per line, up to {LIMITS.questions}.
          </p>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <label htmlFor={`${id}-urls`} className={labelClass}>
              URLs to read
            </label>
            <textarea
              id={`${id}-urls`}
              className={inputClass}
              rows={3}
              value={fields.urls}
              onChange={(e) => set("urls", e.target.value)}
              aria-describedby={`${id}-urls-hint`}
              placeholder="https://…"
              disabled={busy}
            />
            <p id={`${id}-urls-hint`} className={hintClass}>
              Public pages only, up to {LIMITS.userUrls}. robots.txt is respected. In offline
              mode only recorded pages are available.
            </p>
          </div>
          <div>
            <label htmlFor={`${id}-docs`} className={labelClass}>
              Documents
            </label>
            <input
              id={`${id}-docs`}
              ref={fileRef}
              type="file"
              multiple
              accept={DOCUMENT_EXTENSIONS.join(",")}
              onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
              aria-describedby={`${id}-docs-hint`}
              className="mt-1 block w-full text-sm file:mr-3 file:rounded-md file:border file:border-zinc-300 file:bg-white file:px-3 file:py-1.5 file:text-sm dark:file:border-zinc-700 dark:file:bg-zinc-900"
              disabled={busy}
            />
            <p id={`${id}-docs-hint`} className={hintClass}>
              .txt or .md, up to {LIMITS.documents} files of {formatBytes(LIMITS.uploadBytes)} each.
            </p>
            {files.length > 0 && (
              <ul className="mt-2 space-y-1 text-xs">
                {files.map((f) => (
                  <li key={f.name}>
                    {f.name} · {formatBytes(f.size)}
                  </li>
                ))}
                <li>
                  <button
                    type="button"
                    className="text-sky-700 underline dark:text-sky-300"
                    onClick={() => {
                      setFiles([]);
                      if (fileRef.current) fileRef.current.value = "";
                    }}
                    disabled={busy}
                  >
                    Clear files
                  </button>
                </li>
              </ul>
            )}
          </div>
        </div>

        <div className="flex flex-wrap items-end gap-4">
          <div>
            <label htmlFor={`${id}-max`} className={labelClass}>
              Number of sources
            </label>
            <input
              id={`${id}-max`}
              type="number"
              min={1}
              max={LIMITS.maxSources}
              className={`${inputClass} w-28`}
              value={Number.isNaN(fields.maxSources) ? "" : fields.maxSources}
              onChange={(e) => set("maxSources", e.target.valueAsNumber)}
              disabled={busy}
            />
          </div>
          <div>
            <label htmlFor={`${id}-format`} className={labelClass}>
              Output format
            </label>
            <select id={`${id}-format`} className={`${inputClass} w-36`} disabled={busy} defaultValue="markdown">
              <option value="markdown">Markdown</option>
            </select>
          </div>
          <div className="ml-auto flex items-center gap-3">
            {progress && (
              <p className="text-sm text-zinc-600 dark:text-zinc-400" role="status" aria-live="polite">
                {progress}
              </p>
            )}
            <button type="submit" className={buttonClass.primary} disabled={busy}>
              {busy ? "Working…" : "Start research"}
            </button>
          </div>
        </div>
      </form>
    </Card>
  );
}
