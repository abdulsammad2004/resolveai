"use client";

import { ExternalLink, Plus, UserRound } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { FormError } from "@/components/auth/form-error";
import { contactName, shortTime } from "@/components/conversations/conversations-view";
import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { NewTicketDialog } from "@/components/tickets/new-ticket-dialog";
import {
  IntentChip,
  PRIORITIES,
  PriorityChip,
  TicketStatusChip,
  priorityLabel,
} from "@/components/tickets/ticket-chips";
import { TicketPanel } from "@/components/tickets/ticket-panel";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { errorMessage } from "@/lib/api/errors";
import {
  useTickets,
  type TicketPriority,
  type TicketStatus,
  type TicketSummary,
} from "@/lib/api/queries";
import { cn, initials } from "@/lib/utils";

type Tab = "all" | Extract<TicketStatus, "new" | "triaged" | "resolved">;
const TABS: { value: Tab; label: string }[] = [
  { value: "all", label: "All" },
  { value: "new", label: "New" },
  { value: "triaged", label: "Triaged" },
  { value: "resolved", label: "Resolved" },
];

export function TicketsView() {
  const [tab, setTab] = useState<Tab>("all");
  const [priority, setPriority] = useState<TicketPriority | "">("");
  const [mine, setMine] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const tickets = useTickets({
    status: tab === "all" ? undefined : tab,
    priority: priority || undefined,
    assignee: mine ? "me" : "any",
  });
  const items = tickets.data?.pages.flatMap((p) => p.items) ?? [];
  const counts = tickets.data?.pages[0]?.counts;
  const total = counts ? counts.open + counts.resolved : undefined;

  const newTicket = (
    <Button onClick={() => setCreating(true)} className="gap-1.5">
      <Plus className="size-4" aria-hidden />
      New ticket
    </Button>
  );
  const dialog = (
    <NewTicketDialog
      open={creating}
      onOpenChange={setCreating}
      onCreated={(id) => {
        setSelected(id);
        setTab("all");
        setPriority("");
        setMine(false);
      }}
    />
  );

  if (tickets.isSuccess && total === 0) {
    return (
      <div className="flex flex-col gap-4">
        <PageHeader title="Inbox" />
        <EmptyState
          illustration="inbox"
          title="Your inbox is clear"
          action={
            <div className="flex flex-wrap gap-3">
              {newTicket}
              <Button asChild variant="secondary">
                <Link href="/widget-demo" target="_blank" rel="noopener">
                  Chat on the demo page
                  <ExternalLink className="size-3.5" aria-hidden />
                </Link>
              </Button>
            </div>
          }
        >
          Every widget message is classified as it arrives. Refunds, complaints, order and account
          requests, and anything the assistant can&apos;t answer from your docs land here as
          tickets, urgent ones first. You can also log a ticket by hand.
        </EmptyState>
        {dialog}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <PageHeader
          title="Inbox"
          description="Customer requests that need a person, urgent first."
        />
        <div className="pb-1">{newTicket}</div>
      </div>

      <div className="grid min-h-[32rem] gap-4 lg:h-[calc(100dvh-15rem)] lg:grid-cols-[minmax(20rem,28rem)_1fr]">
        <section
          aria-label="Ticket list"
          className={cn(
            "flex min-h-0 flex-col overflow-hidden rounded-panel border border-line bg-carbon",
            selected && "hidden lg:flex",
          )}
        >
          <div className="flex flex-col gap-2 border-b border-line p-2">
            <div role="tablist" aria-label="Filter by status" className="flex gap-1 overflow-x-auto">
              {TABS.map((t) => {
                const count = t.value === "all" ? total : counts?.[t.value];
                return (
                  <button
                    key={t.value}
                    type="button"
                    role="tab"
                    aria-selected={tab === t.value}
                    onClick={() => setTab(t.value)}
                    className={cn(
                      "pressable flex h-8 shrink-0 items-center gap-1.5 rounded-[6px] px-2.5 text-xs font-medium transition-colors",
                      "focus-visible:ring-2 focus-visible:ring-ion focus-visible:outline-none",
                      tab === t.value
                        ? "bg-white/[0.08] text-bone"
                        : "text-ash hover:bg-white/[0.04] hover:text-bone",
                    )}
                  >
                    {t.label}
                    {count !== undefined && <span className="tabular-nums text-ash">{count}</span>}
                  </button>
                );
              })}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <label htmlFor="priority-filter" className="sr-only">
                Priority
              </label>
              <select
                id="priority-filter"
                value={priority}
                onChange={(e) => setPriority(e.target.value as TicketPriority | "")}
                className="h-8 rounded-[6px] border border-line bg-carbon-input px-2 text-xs text-bone focus-visible:ring-2 focus-visible:ring-ion focus-visible:outline-none"
              >
                <option value="">All priorities</option>
                {[...PRIORITIES].reverse().map((p) => (
                  <option key={p} value={p}>
                    {priorityLabel[p]}
                  </option>
                ))}
              </select>
              <button
                type="button"
                aria-pressed={mine}
                onClick={() => setMine((v) => !v)}
                className={cn(
                  "pressable flex h-8 items-center gap-1.5 rounded-[6px] border px-2.5 text-xs font-medium transition-colors",
                  "focus-visible:ring-2 focus-visible:ring-ion focus-visible:outline-none",
                  mine
                    ? "border-ion/50 bg-ion/10 text-bone"
                    : "border-line text-ash hover:border-line-strong hover:text-bone",
                )}
              >
                <UserRound className="size-3.5" aria-hidden />
                Assigned to me
              </button>
              {counts && counts.urgent_open > 0 && (
                <span className="ml-auto text-xs font-medium text-urgent">
                  {counts.urgent_open} urgent open
                </span>
              )}
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto">
            {tickets.isPending && (
              <ul aria-busy="true" aria-label="Loading tickets" className="flex flex-col gap-4 p-4">
                {[0, 1, 2, 3].map((i) => (
                  <li key={i} className="flex flex-col gap-2">
                    <Skeleton className="h-4 w-2/3" />
                    <Skeleton className="h-3 w-1/2" />
                  </li>
                ))}
              </ul>
            )}
            {tickets.isError && (
              <div className="p-4">
                <FormError>{errorMessage(tickets.error)}</FormError>
              </div>
            )}
            {tickets.isSuccess && items.length === 0 && (
              <p className="p-6 text-sm text-ash">No tickets match these filters.</p>
            )}
            <ul className="divide-y divide-line">
              {items.map((t) => (
                <li key={t.id}>
                  <TicketRow ticket={t} selected={selected === t.id} onSelect={() => setSelected(t.id)} />
                </li>
              ))}
            </ul>
            {tickets.hasNextPage && (
              <div className="p-3">
                <Button
                  variant="ghost"
                  size="sm"
                  className="w-full"
                  onClick={() => void tickets.fetchNextPage()}
                  disabled={tickets.isFetchingNextPage}
                >
                  {tickets.isFetchingNextPage ? "Loading…" : "Load more"}
                </Button>
              </div>
            )}
          </div>
        </section>

        <section
          aria-label="Ticket"
          className={cn(
            "min-h-0 flex-col overflow-hidden rounded-panel border border-line bg-carbon",
            selected ? "flex" : "hidden lg:flex",
          )}
        >
          {selected ? (
            <TicketPanel id={selected} onBack={() => setSelected(null)} />
          ) : (
            <div className="flex flex-1 items-center justify-center p-8 text-center text-sm text-ash">
              Pick a ticket to see the conversation and why it was routed here.
            </div>
          )}
        </section>
      </div>
      {dialog}
    </div>
  );
}

function TicketRow({
  ticket: t,
  selected,
  onSelect,
}: {
  ticket: TicketSummary;
  selected: boolean;
  onSelect: () => void;
}) {
  const urgent = t.priority === "urgent" && t.status !== "resolved";
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-current={selected ? "true" : undefined}
      className={cn(
        "relative flex w-full flex-col gap-2 px-4 py-3 text-left transition-colors",
        "focus-visible:ring-2 focus-visible:ring-ion focus-visible:outline-none focus-visible:ring-inset",
        urgent && "bg-urgent/[0.06]",
        selected ? "bg-white/[0.06]" : "hover:bg-white/[0.03]",
      )}
    >
      {(urgent || selected) && (
        <span
          aria-hidden
          className={cn("absolute inset-y-0 left-0 w-[3px]", urgent ? "bg-urgent" : "bg-ion")}
        />
      )}
      <span className="flex items-start gap-2">
        <span
          className={cn(
            "min-w-0 flex-1 text-sm font-semibold text-bone",
            t.status === "resolved" && "text-ash",
          )}
        >
          <span className="line-clamp-2">{t.subject}</span>
        </span>
        <time dateTime={t.created_at} className="shrink-0 text-xs text-ash">
          {shortTime(t.created_at)}
        </time>
      </span>
      <span className="flex items-center gap-2 text-xs text-ash">
        <span className="min-w-0 flex-1 truncate">
          {t.contact ? contactName(t.contact) : "No contact"} ·{" "}
          {t.source === "widget" ? "Website chat" : "Manual"}
        </span>
        {t.assignee ? (
          <Avatar
            className="size-6 border border-line bg-carbon-elevated text-[10px] font-semibold text-bone"
            title={`Assigned to ${t.assignee.full_name}`}
          >
            <AvatarFallback>{initials(t.assignee.full_name)}</AvatarFallback>
            <span className="sr-only">Assigned to {t.assignee.full_name}</span>
          </Avatar>
        ) : (
          <span className="text-[11px]">Unassigned</span>
        )}
      </span>
      <span className="flex flex-wrap gap-1.5">
        <PriorityChip priority={t.priority} />
        <IntentChip intent={t.intent} />
        <TicketStatusChip status={t.status} />
      </span>
    </button>
  );
}
