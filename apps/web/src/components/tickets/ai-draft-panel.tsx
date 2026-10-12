"use client";

import { Copy, PenLine, RotateCcw, Send, Sparkles, X } from "lucide-react";
import { useId, useState } from "react";
import { toast } from "sonner";

import { StatusChip, type ChipTone } from "@/components/status-chip";
import { Button } from "@/components/ui/button";
import { ReasonDialog } from "@/components/tickets/reason-dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { CitedAnswer } from "@/components/widget/cited-answer";
import { errorMessage } from "@/lib/api/errors";
import {
  useEditDraft,
  useRejectDraft,
  useSendDraft,
  useWriteReply,
  type ReplyDraft,
  type TicketDetail,
} from "@/lib/api/queries";
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

const REVIEWABLE: ReadonlySet<ReplyDraft["status"]> = new Set(["pending", "edited"]);

export function AiDraftPanel({
  ticket,
  awaiting,
  regenerating,
  onRegenerate,
}: {
  ticket: TicketDetail;
  awaiting: boolean;
  regenerating: boolean;
  onRegenerate: () => void;
}) {
  const draft = ticket.draft ?? null;
  const send = useSendDraft();
  const edit = useEditDraft();
  const reject = useRejectDraft();
  const writeReply = useWriteReply();
  const editorId = useId();

  // The text being edited, or null when the draft is shown read-only. Keyed by draft id so
  // switching tickets (or a new draft arriving) never carries text over.
  const [editing, setEditing] = useState<{ draftId: string; text: string } | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const busy = send.isPending || edit.isPending || reject.isPending || writeReply.isPending;

  const failed = draft?.status === "failed";
  const reviewable = !!draft && REVIEWABLE.has(draft.status) && !awaiting;
  const human = draft?.author_type === "human";
  // A blank reply someone just started opens straight in the editor.
  const editorText =
    editing && editing.draftId === draft?.id
      ? editing.text
      : reviewable && human && draft.content === ""
        ? ""
        : null;
  const isEditing = reviewable && editorText !== null;
  const canSend = ticket.conversation !== null && ticket.conversation !== undefined;
  const showDraft = draft && !failed && !awaiting && !isEditing && draft.content !== "";

  async function run(action: () => Promise<unknown>, done: string): Promise<boolean> {
    try {
      await action();
      setEditing(null);
      toast.success(done);
      return true;
    } catch (error) {
      toast.error(errorMessage(error));
      return false;
    }
  }

  function sendDraft() {
    if (!draft) return;
    const content = isEditing ? editorText.trim() : undefined;
    if (content === "") {
      toast.error("Write a reply before sending it.");
      return;
    }
    void run(
      () => send.mutateAsync({ ticketId: ticket.id, draftId: draft.id, content }),
      "Reply sent to the customer.",
    );
  }

  function saveEdits() {
    if (!draft || editorText === null) return;
    const content = editorText.trim();
    if (!content) {
      toast.error("Write a reply before saving it.");
      return;
    }
    void run(() => edit.mutateAsync({ ticketId: ticket.id, draftId: draft.id, content }), "Edits saved.");
  }

  async function copy() {
    if (!draft) return;
    try {
      await navigator.clipboard.writeText(plainText(draft.content));
      toast.success("Draft copied.");
    } catch {
      toast.error("Couldn't copy. Select the text and copy it instead.");
    }
  }

  const sendLabel = draft?.status === "pending" && !isEditing ? "Approve & send" : "Send";

  return (
    <section
      aria-labelledby="ai-draft"
      aria-busy={awaiting || undefined}
      className={cn(
        "flex flex-col gap-3 rounded-panel border bg-carbon-input p-4",
        reviewable ? "border-review/30" : "border-line",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        {human ? (
          <PenLine className="size-4 text-ion" aria-hidden />
        ) : (
          <Sparkles className="size-4 text-ion" aria-hidden />
        )}
        <h3 id="ai-draft" className="text-sm font-semibold text-bone">
          {human ? "Your reply" : "AI draft"}
        </h3>
        {awaiting ? (
          <StatusChip tone="ion" dot>
            Writing
          </StatusChip>
        ) : (
          draft &&
          !(human && draft.status === "edited") && (
            <StatusChip tone={draftStatusTone[draft.status]}>{draftStatusLabel[draft.status]}</StatusChip>
          )
        )}
        {draft && !awaiting && (
          <span className="text-xs text-ash">
            {draft.status === "sent" && draft.sent_at
              ? `Sent ${timeFormat.format(new Date(draft.sent_at))}`
              : `${failed ? "Tried" : human ? "Started" : "Written"} ${timeFormat.format(new Date(draft.created_at))}`}
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
          order lookups and your help articles, or write the reply yourself.
        </p>
      )}

      {isEditing && (
        <div className="flex flex-col gap-1.5">
          <label htmlFor={editorId} className="text-xs text-ash">
            {human ? "Reply to the customer" : "Edit the reply before sending"}
          </label>
          <Textarea
            id={editorId}
            value={editorText}
            onChange={(e) => setEditing({ draftId: draft.id, text: e.target.value })}
            rows={7}
            maxLength={5000}
            autoFocus
            disabled={busy}
          />
          {!human && (
            <p className="text-xs text-ash">
              Source markers like [S1] become citations the customer can open. Remove one to drop it.
            </p>
          )}
        </div>
      )}

      {showDraft && (
        <div className="text-bone/95">
          <CitedAnswer content={draft.content} citations={draft.citations} compact />
        </div>
      )}

      {!awaiting && draft?.status === "rejected" && (
        <p className="text-xs text-ash">
          Rejected{draft.rejection_reason ? `: “${draft.rejection_reason}”` : "."} Regenerate it or
          write the reply yourself.
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2 pt-1">
        {reviewable && (
          <Button
            size="sm"
            onClick={sendDraft}
            disabled={busy || !canSend}
            className="gap-1.5"
            title={canSend ? undefined : "This ticket has no chat to reply in"}
          >
            <Send className="size-3.5" aria-hidden />
            {send.isPending ? "Sending…" : sendLabel}
          </Button>
        )}
        {reviewable && isEditing && (
          <>
            <Button size="sm" variant="secondary" onClick={saveEdits} disabled={busy}>
              Save
            </Button>
            {!(human && draft.content === "") && (
              <Button size="sm" variant="ghost" onClick={() => setEditing(null)} disabled={busy}>
                Cancel
              </Button>
            )}
          </>
        )}
        {reviewable && !isEditing && (
          <Button
            size="sm"
            variant="secondary"
            onClick={() => setEditing({ draftId: draft.id, text: draft.content })}
            disabled={busy}
            className="gap-1.5"
          >
            <PenLine className="size-3.5" aria-hidden />
            Edit
          </Button>
        )}
        {reviewable && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setRejecting(true)}
            disabled={busy}
            className="gap-1.5"
          >
            <X className="size-3.5" aria-hidden />
            {human ? "Discard" : "Reject"}
          </Button>
        )}
        <Button
          size="sm"
          variant="ghost"
          onClick={onRegenerate}
          disabled={awaiting || regenerating || busy}
          className="gap-1.5"
        >
          <RotateCcw className="size-3.5" aria-hidden />
          {draft && !human ? "Regenerate" : "Generate AI draft"}
        </Button>
        {!(reviewable && human) && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => void run(() => writeReply.mutateAsync(ticket.id), "Started a new reply.")}
            disabled={awaiting || busy}
            className="gap-1.5"
          >
            <PenLine className="size-3.5" aria-hidden />
            Write reply
          </Button>
        )}
        {showDraft && (
          <Button size="sm" variant="ghost" onClick={() => void copy()} className="gap-1.5">
            <Copy className="size-3.5" aria-hidden />
            Copy
          </Button>
        )}
      </div>
      <p className="text-xs text-ash">
        {canSend
          ? "Nothing is sent until you choose Send. Sent replies appear in the customer's chat."
          : "This ticket was created by hand, so there is no chat to send to. Copy the text to reply another way."}
      </p>

      <ReasonDialog
        open={rejecting}
        onOpenChange={setRejecting}
        title={human ? "Discard this reply?" : "Reject this draft?"}
        description="Nothing is sent to the customer. You can regenerate a draft or write the reply yourself afterwards."
        confirmLabel={human ? "Discard" : "Reject draft"}
        pending={reject.isPending}
        onConfirm={(reason) => {
          if (!draft) return;
          void run(
            () => reject.mutateAsync({ ticketId: ticket.id, draftId: draft.id, reason }),
            human ? "Reply discarded." : "Draft rejected.",
          ).then((ok) => ok && setRejecting(false));
        }}
      />
    </section>
  );
}

