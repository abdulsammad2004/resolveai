"use client";

import { Search } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";

import { FormError } from "@/components/auth/form-error";
import { GlassPanel } from "@/components/glass-panel";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { errorMessage } from "@/lib/api/errors";
import { useKnowledgeSearch, type SearchResult } from "@/lib/api/queries";

const MAX_QUERY_LENGTH = 500;
const SNIPPET_CHARS = 260;
const STOPWORDS = new Set(
  "the and for are but not you your with can how what when where which who why does did from this that have has was were will our out about into than then them they their there".split(
    " ",
  ),
);

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Query words worth emphasising: 3+ letters, not stopwords. */
function queryTerms(query: string): string[] {
  const words = query.toLowerCase().match(/[\p{L}\p{N}]{3,}/gu) ?? [];
  return [...new Set(words.filter((w) => !STOPWORDS.has(w)))];
}

/*
 * Search is semantic, so the passage may not contain the query's words at all. When it
 * does, centre the snippet on the first one and emphasise every occurrence.
 */
function Snippet({ content, terms }: { content: string; terms: string[] }) {
  const text = content.replace(/\s+/g, " ").trim();
  const pattern = terms.length ? new RegExp(`(${terms.map(escapeRegExp).join("|")})`, "giu") : null;

  let start = 0;
  if (pattern) {
    const first = text.search(pattern);
    if (first > SNIPPET_CHARS / 3) start = first - Math.floor(SNIPPET_CHARS / 3);
  }
  let end = Math.min(text.length, start + SNIPPET_CHARS);
  // Don't cut words in half.
  if (start > 0) start = text.indexOf(" ", start) + 1 || start;
  if (end < text.length) end = text.lastIndexOf(" ", end) > start ? text.lastIndexOf(" ", end) : end;
  const window = text.slice(start, end);

  const parts: ReactNode[] = pattern
    ? window.split(pattern).map((part, i) =>
        i % 2 === 1 ? (
          <mark key={i} className="rounded-[3px] bg-ion/20 px-0.5 font-medium text-bone">
            {part}
          </mark>
        ) : (
          part
        ),
      )
    : [window];

  return (
    <p className="text-sm leading-relaxed text-ash">
      {start > 0 && "… "}
      {parts}
      {end < text.length && " …"}
    </p>
  );
}

function ScoreBar({ score }: { score: number }) {
  const pct = Math.round(Math.max(0, Math.min(1, score)) * 100);
  return (
    <div className="flex items-center gap-2" title="Cosine similarity between your query and this passage">
      <div className="h-1 w-16 overflow-hidden rounded-full bg-white/[0.08]" aria-hidden>
        <div className="h-full rounded-full bg-ion" style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs tabular-nums text-ash">
        <span className="sr-only">Similarity </span>
        {score.toFixed(2)}
      </span>
    </div>
  );
}

function ResultItem({ result, terms }: { result: SearchResult; terms: string[] }) {
  const location = [
    ...result.heading_path,
    ...(result.page_number != null ? [`Page ${result.page_number}`] : []),
  ];
  return (
    <li className="flex flex-col gap-2 rounded-[10px] border border-line bg-carbon-elevated p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-bone">{result.document_title}</p>
          {location.length > 0 && (
            <p className="truncate text-xs text-ash">{location.join(" › ")}</p>
          )}
        </div>
        <ScoreBar score={result.score} />
      </div>
      <Snippet content={result.content} terms={terms} />
    </li>
  );
}

export function SearchPanel({ readyCount }: { readyCount: number }) {
  const search = useKnowledgeSearch();
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    const q = query.trim();
    if (!q || search.isPending) return;
    setSubmitted(q);
    search.mutate(q);
  }

  const terms = queryTerms(submitted);

  return (
    <GlassPanel aria-labelledby="test-search-title" className="flex flex-col gap-4 p-5 sm:p-6">
      <div className="flex flex-col gap-1">
        <h2 id="test-search-title" className="text-lg font-semibold text-bone">
          Test search
        </h2>
        <p className="text-sm text-ash">
          Ask what a customer might ask and see which passages the assistant would cite.
        </p>
      </div>

      <form onSubmit={onSubmit} role="search" className="flex flex-col gap-2 sm:flex-row">
        <label htmlFor="knowledge-search" className="sr-only">
          Search your documents
        </label>
        <Input
          id="knowledge-search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          maxLength={MAX_QUERY_LENGTH}
          placeholder="How long do refunds take?"
          autoComplete="off"
        />
        <Button type="submit" disabled={!query.trim() || search.isPending} className="sm:w-auto">
          <Search aria-hidden />
          {search.isPending ? "Searching…" : "Search"}
        </Button>
      </form>

      {readyCount === 0 && (
        <p className="text-xs text-ash">
          Search covers ready documents only. Results appear once a document finishes processing.
        </p>
      )}

      <div aria-live="polite" aria-busy={search.isPending}>
        {search.isPending && (
          <ul className="flex flex-col gap-3" aria-label="Searching">
            {[0, 1, 2].map((i) => (
              <li key={i} className="flex flex-col gap-2.5 rounded-[10px] border border-line p-4">
                <div className="flex justify-between gap-3">
                  <Skeleton className="h-3.5 w-2/5" />
                  <Skeleton className="h-3 w-16" />
                </div>
                <Skeleton className="h-3 w-1/4" />
                <Skeleton className="h-3 w-full" />
                <Skeleton className="h-3 w-4/5" />
              </li>
            ))}
          </ul>
        )}
        {search.isError && <FormError>{errorMessage(search.error)}</FormError>}
        {search.isSuccess &&
          (search.data.results.length === 0 ? (
            <p className="rounded-[10px] border border-line bg-carbon-elevated p-4 text-sm text-ash">
              No passage in your documents matches this closely enough.
            </p>
          ) : (
            <ol className="flex flex-col gap-3" aria-label={`Results for ${submitted}`}>
              {search.data.results.map((r) => (
                <ResultItem key={r.chunk_id} result={r} terms={terms} />
              ))}
            </ol>
          ))}
      </div>
    </GlassPanel>
  );
}
