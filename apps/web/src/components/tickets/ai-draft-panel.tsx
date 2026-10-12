"use client";

import { Copy, RotateCcw, Sparkles } from "lucide-react";
import { toast } from "sonner";

import { StatusChip, type ChipTone } from "@/components/status-chip";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { CitedAnswer } from "@/components/widget/cited-answer";
import type { ReplyDraft, TicketDetail } from "@/lib/api/queries";
import { cn } from "@/lib/utils";

/** How long the panel waits (skeleton + fast polling) for a draft job before giving up. */
export const DRAFT_WAIT_MS = 3 * 60_000;

/** A regenerate request: waiting until a draft other than `previousDraftId` shows up. */
export type DraftRequest = { at: number; previousDraftId: string | null };

const timeFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

const draftStatusLabel: Record<ReplyDraft["status"], string> = {
  pending: "Pending review",
  approved: "Approved",
  edited: "Edited",
  rejected: "Rejected",
  sent: "Sent",
  superseded: "Replaced",
  failed: "Failed",
};

const draftStatusTone: Record<ReplyDraft["status"], ChipTone> = {
  pending: "review",
  approved: "ion",
  edited: "ion",
  rejected: "neutral",
  sent: "resolved",
  superseded: "neutral",
  failed: "urgent",
};

/**
 * Whether a draft job is (probably) still running: right after the ticket was created with
 * no draft yet, or after Regenerate until a different draft appears. Both time out.
 */
export function isAwaitingDraft(ticket: TicketDetail, request: DraftRequest | null, now: number) {
  if (ticket.status === "resolved") return false;
  const draftId = ticket.draft?.id ?? null;
  if (request && draftId === request.previousDraftId && now - request.at < DRAFT_WAIT_MS) {
    return true;
  }
  return draftId === null && now - Date.parse(ticket.created_at) < DRAFT_WAIT_MS;
}

/** The draft as plain text for pasting: source markers removed. */
function plainText(content: string): string {
  return content
    .replace(/\s*\[S\d+\]/g, "")
    .replace(/[ \t]{2,}/g, " ")
    .trim();
}

export function AiDraftPanel({
  draft,
  awaiting,
  regenerating,
  onRegenerate,
}: {
  draft: ReplyDraft | null;
  awaiting: boolean;
  regenerating: boolean;
  onRegenerate: () => void;
}) {
  async function copy() {
    if (!draft) return;
    try {
      await navigator.clipboard.writeText(plainText(draft.content));
      toast.success("Draft copied.");
    } catch {
      toast.error("Couldn't copy. Select the text and copy it instead.");
    }
  }

  const failed = draft?.status === "failed";
  const showDraft = draft && !failed && !awaiting;

  return (
    <section
      aria-labelledby="ai-draft"
      aria-busy={awaiting || undefined}
      className={cn(
        "flex flex-col gap-3 rounded-panel border bg-carbon-input p-4",
        showDraft && draft.status === "pending" ? "border-review/30" : "border-line",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <Sparkles className="size-4 text-ion" aria-hidden />
        <h3 id="ai-draft" className="text-sm font-semibold text-bone">
          AI draft
        </h3>
        {awaiting ? (
          <StatusChip tone="ion" dot>
            Writing
          </StatusChip>
        ) : (
          draft && (
            <StatusChip tone={draftStatusTone[draft.status]}>{draftStatusLabel[draft.status]}</StatusChip>
          )
        )}
        {draft && !awaiting && (
          <span className="text-xs text-ash">
            {failed ? "Tried" : "Written"} {timeFormat.format(new Date(draft.created_at))}
          </span>
        )}
      </div>

      {awaiting && (
        <div className="flex flex-col gap-2" aria-label="Writing a draft">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-11/12" />
          <Skeleton className="h-4 w-3/5" />
          <p className="pt-1 text-xs text-ash">
            The assistant is reading the conversation and checking orders and help articles.
          </p>
        </div>
      )}

      {!awaiting && failed && (
        <p role="alert" className="text-sm text-bone/90">
          {draft.error || "The assistant couldn't write a draft."} Try regenerating it.
        </p>
      )}

      {!awaiting && !draft && (
        <p className="text-sm text-ash">
          No draft yet. Generate one and the assistant will write a reply from the conversation,
          order lookups and your help articles.
        </p>
      )}

      {showDraft && (
        <div className="text-bone/95">
          <CitedAnswer content={draft.content} citations={draft.citations} compact />
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 pt-1">
        <Button
          size="sm"
          variant="secondary"
          onClick={onRegenerate}
          disabled={awaiting || regenerating}
          className="gap-1.5"
        >
          <RotateCcw className="size-3.5" aria-hidden />
          {draft ? "Regenerate draft" : "Generate draft"}
        </Button>
        {showDraft && (
          <Button size="sm" variant="ghost" onClick={() => void copy()} className="gap-1.5">
            <Copy className="size-3.5" aria-hidden />
            Copy
          </Button>
        )}
      </div>
      <p className="text-xs text-ash">
        Drafts are never sent automatically. Approving and sending them from here arrives in the
        next update. Until then, copy the text to use it.
      </p>
    </section>
  );
}
