"use client";

import { ArrowLeft, CircleCheck, ThumbsDown, ThumbsUp, UserRound } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { toast } from "sonner";

import { FormError } from "@/components/auth/form-error";
import { contactName, Transcript } from "@/components/conversations/conversations-view";
import { ActivityLog } from "@/components/tickets/activity-log";
import {
  AiDraftPanel,
  isAwaitingDraft,
  type DraftRequest,
} from "@/components/tickets/ai-draft-panel";
import { ProposedActions } from "@/components/tickets/proposed-actions";
import {
  PRIORITIES,
  STATUSES,
  intentText,
  priorityLabel,
  statusLabel,
} from "@/components/tickets/ticket-chips";
import { ToolActivity } from "@/components/tickets/tool-activity";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { errorMessage } from "@/lib/api/errors";
import {
  useRegenerateDraft,
  useTicket,
  useUpdateTicket,
  type Classification,
  type TicketDetail,
  type TicketPriority,
  type TicketStatus,
  type TicketUpdate,
} from "@/lib/api/queries";
import { useAuth } from "@/lib/auth/auth-provider";
import { cn } from "@/lib/utils";

const fullFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });
const SELECT_CLASS =
  "h-9 rounded-[6px] border border-line bg-carbon-input px-2 text-sm text-bone focus-visible:ring-2 focus-visible:ring-ion focus-visible:outline-none disabled:opacity-50";

const AWAIT_TICK_MS = 5_000;

export function TicketPanel({ id, onBack }: { id: string; onBack: () => void }) {
  // A Regenerate click on this ticket: show the skeleton until a different draft arrives.
  const [request, setRequest] = useState<(DraftRequest & { ticketId: string }) | null>(null);
  const activeRequest = request?.ticketId === id ? request : null;
  const ticket = useTicket(id, {
    awaitingDraft: (t) => isAwaitingDraft(t, activeRequest, Date.now()),
  });
  const [now, setNow] = useState(() => Date.now());
  const awaiting = ticket.data ? isAwaitingDraft(ticket.data, activeRequest, now) : false;

  // Re-check while waiting so the skeleton gives up after DRAFT_WAIT_MS.
  useEffect(() => {
    if (!awaiting) return;
    const timer = window.setInterval(() => setNow(Date.now()), AWAIT_TICK_MS);
    return () => window.clearInterval(timer);
  }, [awaiting]);

  if (ticket.isPending) {
    return (
      <div aria-busy="true" aria-label="Loading ticket" className="flex flex-col gap-4 p-6">
        <Skeleton className="h-7 w-2/3" />
        <Skeleton className="h-9 w-full max-w-md" />
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }
  if (ticket.isError) {
    return (
      <div className="p-6">
        <FormError>{errorMessage(ticket.error)}</FormError>
      </div>
    );
  }
  return (
    <TicketBody
      ticket={ticket.data}
      onBack={onBack}
      awaitingDraft={awaiting}
      onDraftRequested={() => {
        const at = Date.now();
        setNow(at);
        setRequest({ ticketId: id, at, previousDraftId: ticket.data.draft?.id ?? null });
      }}
    />
  );
}

function TicketBody({
  ticket: t,
  onBack,
  awaitingDraft,
  onDraftRequested,
}: {
  ticket: TicketDetail;
  onBack: () => void;
  awaitingDraft: boolean;
  onDraftRequested: () => void;
}) {
  const { user } = useAuth();
  const update = useUpdateTicket();
  const regenerate = useRegenerateDraft();

  async function regenerateDraft() {
    try {
      await regenerate.mutateAsync(t.id);
      onDraftRequested();
    } catch (error) {
      toast.error(errorMessage(error));
    }
  }
  const statusId = useId();
  const priorityId = useId();
  const assignedToMe = t.assignee?.user_id === user?.id;

  async function change(changes: TicketUpdate, done: string) {
    try {
      await update.mutateAsync({ id: t.id, changes });
      toast.success(done);
    } catch (error) {
      toast.error(errorMessage(error));
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <header className="flex flex-col gap-4 border-b border-line px-4 py-4 sm:px-6">
        <div className="flex items-start gap-3">
          <Button variant="ghost" size="icon" className="-ml-2 lg:hidden" onClick={onBack} aria-label="Back to the list">
            <ArrowLeft className="size-4" aria-hidden />
          </Button>
          <div className="min-w-0 flex-1">
            <h2 className="font-display text-2xl leading-tight font-bold tracking-tight text-bone break-words">
              {t.subject}
            </h2>
            <p className="mt-1 text-xs text-ash">
              {t.contact ? contactName(t.contact) : "No contact"}
              {t.contact?.email && t.contact.email !== contactName(t.contact) && ` · ${t.contact.email}`}
              {" · "}
              {t.source === "widget" ? "Website chat" : "Created by hand"} · {fullFormat.format(new Date(t.created_at))}
            </p>
            {t.resolution_rating && (
              <p className="mt-1.5 flex items-center gap-1.5 text-xs text-bone/90">
                {t.resolution_rating === "up" ? (
                  <ThumbsUp className="size-3.5 text-resolved" aria-hidden />
                ) : (
                  <ThumbsDown className="size-3.5 text-urgent" aria-hidden />
                )}
                Customer rated the resolution {t.resolution_rating === "up" ? "helpful" : "not helpful"}
              </p>
            )}
          </div>
        </div>

        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1">
            <label htmlFor={statusId} className="text-xs text-ash">
              Status
            </label>
            <select
              id={statusId}
              value={t.status}
              disabled={update.isPending}
              onChange={(e) => {
                const status = e.target.value as TicketStatus;
                void change({ status }, `Marked ${statusLabel[status].toLowerCase()}.`);
              }}
              className={SELECT_CLASS}
            >
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {statusLabel[s]}
                </option>
              ))}
            </select>
          </div>
          {t.status === "replied" && (
            <Button
              size="sm"
              variant="secondary"
              className="h-9 gap-1.5"
              disabled={update.isPending}
              onClick={() => void change({ status: "resolved" }, "Marked resolved.")}
            >
              <CircleCheck className="size-3.5" aria-hidden />
              Mark resolved
            </Button>
          )}
          <div className="flex flex-col gap-1">
            <label htmlFor={priorityId} className="text-xs text-ash">
              Priority
            </label>
            <select
              id={priorityId}
              value={t.priority}
              disabled={update.isPending}
              onChange={(e) => {
                const priority = e.target.value as TicketPriority;
                void change({ priority }, `Priority set to ${priorityLabel[priority].toLowerCase()}.`);
              }}
              className={cn(SELECT_CLASS, t.priority === "urgent" && "border-urgent/50 text-urgent")}
            >
              {[...PRIORITIES].reverse().map((p) => (
                <option key={p} value={p}>
                  {priorityLabel[p]}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-xs text-ash">Assignee</span>
            <div className="flex h-9 items-center gap-2">
              <span className="text-sm text-bone">
                {t.assignee ? (assignedToMe ? "You" : t.assignee.full_name) : "Unassigned"}
              </span>
              {user && !assignedToMe && (
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={update.isPending}
                  onClick={() => void change({ assignee_id: user.id }, "Assigned to you.")}
                  className="gap-1.5"
                >
                  <UserRound className="size-3.5" aria-hidden />
                  Assign to me
                </Button>
              )}
              {t.assignee && (
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={update.isPending}
                  onClick={() => void change({ assignee_id: null }, "Unassigned.")}
                >
                  Unassign
                </Button>
              )}
            </div>
          </div>
        </div>
      </header>

      <div className="flex flex-col gap-6 px-4 py-5 sm:px-6">
        {t.description && (
          <section aria-labelledby="ticket-description" className="flex flex-col gap-2">
            <h3 id="ticket-description" className="text-sm font-semibold text-bone">
              Description
            </h3>
            <p className="text-sm leading-relaxed whitespace-pre-wrap text-bone/90">{t.description}</p>
          </section>
        )}

        <AiDraftPanel
          ticket={t}
          awaiting={awaitingDraft}
          regenerating={regenerate.isPending}
          onRegenerate={() => void regenerateDraft()}
        />

        <ProposedActions actions={t.actions} />

        <ToolActivity calls={t.tool_calls} />

        <ActivityLog events={t.activity} />

        <WhyRouted classification={t.classification ?? null} />

        <section aria-labelledby="ticket-transcript" className="flex flex-col gap-2">
          <h3 id="ticket-transcript" className="text-sm font-semibold text-bone">
            Conversation
          </h3>
          {t.conversation ? (
            <div className="-mx-4 rounded-panel border border-line sm:mx-0">
              <Transcript conversation={t.conversation} />
            </div>
          ) : (
            <p className="text-sm text-ash">This ticket was created by hand, without a chat.</p>
          )}
        </section>
      </div>
    </div>
  );
}

function ProbabilityBar({
  label,
  value,
  highlight = false,
  tone = "ion",
}: {
  label: string;
  value: number;
  highlight?: boolean;
  tone?: "ion" | "review" | "urgent";
}) {
  const pct = Math.round(value * 100);
  return (
    <li className="grid grid-cols-[minmax(7rem,9rem)_1fr_2.75rem] items-center gap-3 text-xs">
      <span className={cn("truncate", highlight ? "font-semibold text-bone" : "text-ash")}>{label}</span>
      <span aria-hidden className="h-1.5 overflow-hidden rounded-full bg-white/[0.06]">
        <span
          className={cn(
            "block h-full rounded-full",
            tone === "urgent" ? "bg-urgent" : tone === "review" ? "bg-review" : "bg-ion",
            !highlight && "opacity-50",
          )}
          style={{ width: `${Math.max(pct, value > 0 ? 2 : 0)}%` }}
        />
      </span>
      <span className={cn("text-right tabular-nums", highlight ? "text-bone" : "text-ash")}>{pct}%</span>
    </li>
  );
}

function WhyRouted({ classification: c }: { classification: Classification | null }) {
  if (!c) {
    return (
      <section aria-labelledby="why-routed" className="flex flex-col gap-2">
        <h3 id="why-routed" className="text-sm font-semibold text-bone">
          Why it was routed here
        </h3>
        <p className="text-sm text-ash">
          No classification was available (the classifier was down or the daily budget was used up).
        </p>
      </section>
    );
  }
  const intents = Object.entries(c.intent_probs).sort((a, b) => b[1] - a[1]);
  const needsHuman = c.needs_human_prob;
  return (
    <section
      aria-labelledby="why-routed"
      className="flex flex-col gap-4 rounded-panel border border-line bg-carbon-input p-4"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id="why-routed" className="text-sm font-semibold text-bone">
          Why it was routed here
        </h3>
        <span className="font-mono text-[11px] text-ash">
          {c.provider === "cloudflare" ? "Clef-flash" : c.provider} · {c.model}
        </span>
      </div>
      <p className="text-sm text-bone/90">
        Classified as <strong className="text-bone">{intentText(c.intent).toLowerCase()}</strong> with{" "}
        {Math.round(c.confidence * 100)}% confidence, {c.priority} priority, and a{" "}
        {Math.round(needsHuman * 100)}% chance it needs a person.
      </p>

      <div className="flex flex-col gap-2">
        <ul aria-label="Needs-a-person probability">
          <ProbabilityBar
            label="Needs a person"
            value={needsHuman}
            highlight
            tone={needsHuman >= 0.7 ? "review" : "ion"}
          />
        </ul>
      </div>

      <div className="flex flex-col gap-2">
        <h4 className="text-xs font-medium text-ash">Intent</h4>
        <ul className="flex flex-col gap-1.5" aria-label="Intent probabilities">
          {intents.map(([intent, p]) => (
            <ProbabilityBar key={intent} label={intentText(intent)} value={p} highlight={intent === c.intent} />
          ))}
        </ul>
      </div>

      <div className="flex flex-col gap-2">
        <h4 className="text-xs font-medium text-ash">Priority</h4>
        <ul className="flex flex-col gap-1.5" aria-label="Priority probabilities">
          {(["urgent", "high", "normal", "low"] as const).map((p) => (
            <ProbabilityBar
              key={p}
              label={priorityLabel[p]}
              value={c.priority_probs[p] ?? 0}
              highlight={p === c.priority}
              tone={p === "urgent" ? "urgent" : p === "high" ? "review" : "ion"}
            />
          ))}
        </ul>
      </div>
    </section>
  );
}
