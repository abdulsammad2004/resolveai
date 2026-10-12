"use client";

import { FileText, X } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

import type { Citation } from "@/lib/widget/api";
import { cn } from "@/lib/utils";

const MARKER = /\[(S\d+)\]/g;

function sourceNumber(sourceId: string): string {
  return sourceId.replace(/^S/, "");
}

function citationLabel(c: Citation): string {
  const section = c.heading_path.at(-1);
  return section && section !== c.title ? `${c.title} · ${section}` : c.title;
}

/**
 * An assistant answer: text with inline [S1] markers turned into small source buttons, and
 * citation chips underneath. Clicking a marker or chip expands the cited snippet.
 */
export function CitedAnswer({
  content,
  citations,
  compact = false,
}: {
  content: string;
  citations: Citation[];
  compact?: boolean;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const panelId = useId();
  const byId = new Map(citations.map((c) => [c.source_id, c]));
  const active = open ? byId.get(open) : undefined;

  function toggle(sourceId: string) {
    setOpen((current) => (current === sourceId ? null : sourceId));
  }

  const parts: ReactNode[] = [];
  let last = 0;
  for (const match of content.matchAll(MARKER)) {
    const citation = byId.get(match[1]);
    if (!citation) continue;
    parts.push(content.slice(last, match.index));
    parts.push(
      <button
        key={`${match.index}-${match[1]}`}
        type="button"
        onClick={() => toggle(match[1])}
        aria-expanded={open === match[1]}
        aria-controls={panelId}
        aria-label={`Source ${sourceNumber(match[1])}: ${citationLabel(citation)}`}
        className={cn(
          "mx-0.5 inline-flex h-4 min-w-4 -translate-y-0.5 items-center justify-center rounded-[3px] px-1 align-middle text-[10px] font-semibold leading-none transition-colors",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ion",
          open === match[1] ? "bg-ion text-ink" : "bg-ion/15 text-ion hover:bg-ion/25",
        )}
      >
        {sourceNumber(match[1])}
      </button>,
    );
    last = (match.index ?? 0) + match[0].length;
  }
  parts.push(content.slice(last));

  return (
    <div className="flex flex-col gap-2.5">
      <p className={cn("whitespace-pre-wrap break-words", compact ? "text-sm" : "text-[15px] leading-relaxed")}>
        {parts}
      </p>

      {citations.length > 0 && (
        <ul className="flex flex-wrap gap-1.5" aria-label="Sources">
          {citations.map((c) => (
            <li key={c.source_id} className="min-w-0 max-w-full">
              <button
                type="button"
                onClick={() => toggle(c.source_id)}
                aria-expanded={open === c.source_id}
                aria-controls={panelId}
                className={cn(
                  "pressable flex h-7 max-w-full items-center gap-1.5 rounded-[6px] border px-2 text-xs transition-colors",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ion",
                  open === c.source_id
                    ? "border-ion/50 bg-ion/10 text-bone"
                    : "border-line bg-white/[0.03] text-ash hover:border-line-strong hover:text-bone",
                )}
              >
                <span className="font-semibold text-ion">{sourceNumber(c.source_id)}</span>
                <FileText className="size-3 shrink-0" aria-hidden />
                <span className="truncate">{citationLabel(c)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}

      <div id={panelId} hidden={!active}>
        {active && (
          <figure className="relative rounded-[6px] border border-line bg-carbon-input p-3 pr-9">
            <figcaption className="mb-1.5 text-xs font-medium text-bone">
              {active.title}
              {active.heading_path.length > 0 && (
                <span className="font-normal text-ash"> · {active.heading_path.join(" › ")}</span>
              )}
            </figcaption>
            <blockquote className="max-h-48 overflow-y-auto whitespace-pre-wrap text-xs leading-relaxed text-ash">
              {active.snippet || "No preview available for this source."}
            </blockquote>
            <button
              type="button"
              onClick={() => setOpen(null)}
              aria-label="Hide source"
              className="absolute top-2 right-2 rounded-[4px] p-1 text-ash hover:bg-white/[0.06] hover:text-bone focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ion"
            >
              <X className="size-3.5" aria-hidden />
            </button>
          </figure>
        )}
      </div>
    </div>
  );
}
