"use client";

import { ArrowLeft, CheckCircle2, ExternalLink, RotateCcw, ThumbsDown, ThumbsUp } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { FormError } from "@/components/auth/form-error";
import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { StatusChip, type ChipTone } from "@/components/status-chip";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { CitedAnswer } from "@/components/widget/cited-answer";
import { errorMessage } from "@/lib/api/errors";
import {
  useConversation,
  useConversations,
  useUpdateConversationStatus,
  type ConversationDetail,
  type ConversationStatus,
  type ConversationSummary,
} from "@/lib/api/queries";
import { cn } from "@/lib/utils";

const statusLabel: Record<ConversationStatus, string> = {
  open: "Open",
  needs_human: "Needs a person",
  closed: "Closed",
};

const statusTone: Record<ConversationStatus, ChipTone> = {
  open: "ion",
  needs_human: "review",
  closed: "neutral",
};

type Filter = ConversationStatus | "all";
const FILTERS: { value: Filter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "needs_human", label: "Needs a person" },
  { value: "open", label: "Open" },
  { value: "closed", label: "Closed" },
];

/** "refund_request" -> "refund request" */
export function intentLabel(intent: string): string {
  return intent.replaceAll("_", " ");
}

const timeFormat = new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" });
const dayFormat = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });
const fullFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

export function shortTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  const sameDay = date.toDateString() === new Date().toDateString();
  return sameDay ? timeFormat.format(date) : dayFormat.format(date);
}

export function contactName(contact: ConversationSummary["contact"]): string {
  return contact.name || contact.email || `Visitor ${contact.anonymous_id.slice(0, 6)}`;
}

export function ConversationsView() {
  const [filter, setFilter] = useState<Filter>("all");
  const [selected, setSelected] = useState<string | null>(null);
  const conversations = useConversations(filter);

  const items = conversations.data?.pages.flatMap((p) => p.items) ?? [];
  const counts = conversations.data?.pages[0]?.counts;
  const total = counts ? counts.open + counts.needs_human + counts.closed : undefined;

  if (conversations.isSuccess && total === 0) {
    return (
      <div className="flex flex-col gap-4">
        <PageHeader title="Conversations" />
        <EmptyState
          illustration="conversations"
          title="No conversations yet"
          action={
            <div className="flex flex-wrap gap-3">
              <Button asChild>
                <Link href="/settings#chat-widget">Set up the chat widget</Link>
              </Button>
              <Button asChild variant="secondary">
                <Link href="/widget-demo" target="_blank" rel="noopener">
                  Try the demo page
                  <ExternalLink className="size-3.5" aria-hidden />
                </Link>
              </Button>
            </div>
          }
        >
          Add the chat widget to your website and customers&apos; questions show up here, with the
          assistant&apos;s cited answers and their thumbs up or down. Chats the assistant
          couldn&apos;t answer are marked <span className="text-review">needs a person</span>.
        </EmptyState>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Conversations"
        description="Customer chats from your website widget, with every answer's sources."
      />

      <div
        className={cn(
          "grid min-h-[32rem] gap-4 lg:grid-cols-[minmax(18rem,24rem)_1fr]",
          "lg:h-[calc(100dvh-14rem)]",
        )}
      >
        <section
          aria-label="Conversation list"
          className={cn(
            "flex min-h-0 flex-col overflow-hidden rounded-panel border border-line bg-carbon",
            selected && "hidden lg:flex",
          )}
        >
          <div role="tablist" aria-label="Filter by status" className="flex gap-1 overflow-x-auto border-b border-line p-2">
            {FILTERS.map((f) => {
              const count = f.value === "all" ? total : counts?.[f.value];
              return (
                <button
                  key={f.value}
                  type="button"
                  role="tab"
                  aria-selected={filter === f.value}
                  onClick={() => setFilter(f.value)}
                  className={cn(
                    "pressable flex h-8 shrink-0 items-center gap-1.5 rounded-[6px] px-2.5 text-xs font-medium transition-colors",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ion",
                    filter === f.value
                      ? "bg-white/[0.08] text-bone"
                      : "text-ash hover:bg-white/[0.04] hover:text-bone",
                  )}
                >
                  {f.label}
                  {count !== undefined && (
                    <span
                      className={cn(
                        "rounded-[4px] px-1 tabular-nums",
                        f.value === "needs_human" && count > 0 ? "bg-review/15 text-review" : "text-ash",
                      )}
                    >
                      {count}
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto">
            {conversations.isPending && (
              <ul aria-busy="true" aria-label="Loading conversations" className="flex flex-col gap-4 p-4">
                {[0, 1, 2, 3].map((i) => (
                  <li key={i} className="flex flex-col gap-2">
                    <Skeleton className="h-4 w-1/2" />
                    <Skeleton className="h-3 w-5/6" />
                  </li>
                ))}
              </ul>
            )}
            {conversations.isError && (
              <div className="p-4">
                <FormError>{errorMessage(conversations.error)}</FormError>
              </div>
            )}
            {conversations.isSuccess && items.length === 0 && (
              <p className="p-6 text-sm text-ash">No conversations with this status.</p>
            )}
            <ul className="divide-y divide-line">
              {items.map((c) => (
                <li key={c.id}>
                  <button
                    type="button"
                    onClick={() => setSelected(c.id)}
                    aria-current={selected === c.id ? "true" : undefined}
                    className={cn(
                      "flex w-full flex-col gap-1.5 px-4 py-3 text-left transition-colors",
                      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ion",
                      selected === c.id
                        ? "bg-white/[0.06] shadow-[inset_2px_0_0_var(--ion)]"
                        : "hover:bg-white/[0.03]",
                    )}
                  >
                    <span className="flex items-center gap-2">
                      <span className="min-w-0 flex-1 truncate text-sm font-semibold text-bone">
                        {contactName(c.contact)}
                      </span>
                      <time dateTime={c.last_message_at ?? undefined} className="shrink-0 text-xs text-ash">
                        {shortTime(c.last_message_at)}
                      </time>
                    </span>
                    <span className="line-clamp-2 text-xs text-ash">
                      {c.last_message_role === "assistant" && <span className="text-bone/70">AI: </span>}
                      {c.last_message_preview?.replace(/\[S\d+\]/g, "")}
                    </span>
                    <StatusChip tone={statusTone[c.status]} dot={c.status === "needs_human"} className="self-start">
                      {statusLabel[c.status]}
                    </StatusChip>
                  </button>
                </li>
              ))}
            </ul>
            {conversations.hasNextPage && (
              <div className="p-3">
                <Button
                  variant="ghost"
                  size="sm"
                  className="w-full"
                  onClick={() => void conversations.fetchNextPage()}
                  disabled={conversations.isFetchingNextPage}
                >
                  {conversations.isFetchingNextPage ? "Loading…" : "Load more"}
                </Button>
              </div>
            )}
          </div>
        </section>

        <section
          aria-label="Conversation"
          className={cn(
            "min-h-0 flex-col overflow-hidden rounded-panel border border-line bg-carbon",
            selected ? "flex" : "hidden lg:flex",
          )}
        >
          {selected ? (
            <ConversationPanel id={selected} onBack={() => setSelected(null)} />
          ) : (
            <div className="flex flex-1 items-center justify-center p-8 text-center text-sm text-ash">
              Pick a conversation to read the transcript.
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function ConversationPanel({ id, onBack }: { id: string; onBack: () => void }) {
  const conversation = useConversation(id);
  const update = useUpdateConversationStatus();

  async function setStatus(status: ConversationStatus) {
    try {
      await update.mutateAsync({ id, status });
      toast.success(status === "closed" ? "Conversation closed." : "Conversation reopened.");
    } catch (error) {
      toast.error(errorMessage(error));
    }
  }

  if (conversation.isPending) {
    return (
      <div aria-busy="true" aria-label="Loading conversation" className="flex flex-col gap-4 p-6">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-16 w-3/4" />
        <Skeleton className="ml-auto h-10 w-1/2" />
      </div>
    );
  }
  if (conversation.isError) {
    return (
      <div className="p-6">
        <FormError>{errorMessage(conversation.error)}</FormError>
      </div>
    );
  }
  const c = conversation.data;

  return (
    <>
      <header className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3 sm:px-6">
        <Button variant="ghost" size="icon" className="lg:hidden" onClick={onBack} aria-label="Back to the list">
          <ArrowLeft className="size-4" aria-hidden />
        </Button>
        <div className="min-w-0 flex-1 basis-48">
          <h2 className="truncate font-display text-2xl font-bold tracking-tight text-bone">
            {contactName(c.contact)}
          </h2>
          <p className="text-xs text-ash">
            Website chat · started {fullFormat.format(new Date(c.created_at))}
          </p>
        </div>
        <StatusChip tone={statusTone[c.status]} dot={c.status === "needs_human"}>
          {statusLabel[c.status]}
        </StatusChip>
        {c.status === "closed" ? (
          <Button variant="secondary" size="sm" onClick={() => void setStatus("open")} disabled={update.isPending}>
            <RotateCcw className="size-3.5" aria-hidden />
            Reopen
          </Button>
        ) : (
          <Button size="sm" onClick={() => void setStatus("closed")} disabled={update.isPending}>
            <CheckCircle2 className="size-3.5" aria-hidden />
            Mark closed
          </Button>
        )}
      </header>
      <Transcript conversation={c} />
    </>
  );
}

export function Transcript({ conversation }: { conversation: ConversationDetail }) {
  return (
    <ol className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-4 py-5 sm:px-6" aria-label="Transcript">
      {conversation.messages.map((m) =>
        m.role === "customer" ? (
          <li key={m.id} className="flex flex-col items-end gap-1">
            <p className="max-w-[85%] whitespace-pre-wrap break-words rounded-[12px] rounded-tr-[4px] border border-ion/30 bg-ion/15 px-3.5 py-2.5 text-sm">
              {m.content}
            </p>
            <span className="text-[11px] text-ash">
              Customer · <time dateTime={m.created_at}>{shortTime(m.created_at)}</time>
              {typeof m.classification?.intent === "string" && (
                <span>
                  {" "}
                  · classified {intentLabel(m.classification.intent)}
                </span>
              )}
            </span>
          </li>
        ) : (
          <li key={m.id} className="flex max-w-[92%] flex-col gap-1.5">
            <div className="rounded-[12px] rounded-tl-[4px] border border-line bg-carbon-elevated px-3.5 py-2.5">
              <CitedAnswer content={m.content} citations={m.citations} compact />
            </div>
            <div className="flex flex-wrap items-center gap-2 text-[11px] text-ash">
              <span>
                {m.role === "assistant" ? "AI assistant" : "Team"} ·{" "}
                <time dateTime={m.created_at}>{shortTime(m.created_at)}</time>
              </span>
              {m.grounded === true && <StatusChip tone="resolved">Grounded</StatusChip>}
              {m.grounded === false && <StatusChip tone="review">Fallback, no sources</StatusChip>}
              {m.route === "handoff" && <StatusChip tone="review">Passed to the team</StatusChip>}
              {m.route === "small_talk" && <StatusChip>Small talk</StatusChip>}
              {m.prompt_version && <span className="font-mono">{m.prompt_version}</span>}
            </div>
            {m.feedback && (
              <p
                className={cn(
                  "flex items-start gap-1.5 rounded-[6px] border px-2.5 py-1.5 text-xs",
                  m.feedback.rating === "up"
                    ? "border-resolved/20 bg-resolved/10 text-bone"
                    : "border-urgent/20 bg-urgent/10 text-bone",
                )}
              >
                {m.feedback.rating === "up" ? (
                  <ThumbsUp className="mt-0.5 size-3 shrink-0 text-resolved" aria-hidden />
                ) : (
                  <ThumbsDown className="mt-0.5 size-3 shrink-0 text-urgent" aria-hidden />
                )}
                <span>
                  Customer rated this {m.feedback.rating === "up" ? "helpful" : "not helpful"}
                  {m.feedback.comment && <span className="text-ash">: “{m.feedback.comment}”</span>}
                </span>
              </p>
            )}
          </li>
        ),
      )}
    </ol>
  );
}
