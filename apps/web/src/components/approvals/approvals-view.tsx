"use client";

import { Info } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { FormError } from "@/components/auth/form-error";
import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { ActionCard } from "@/components/tickets/proposed-actions";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { errorMessage } from "@/lib/api/errors";
import { useActions } from "@/lib/api/queries";
import { useAuth } from "@/lib/auth/auth-provider";
import { cn } from "@/lib/utils";

type Tab = "waiting" | "history";

const TABS: { id: Tab; label: string }[] = [
  { id: "waiting", label: "Waiting" },
  { id: "history", label: "History" },
];

export function ApprovalsView() {
  const [tab, setTab] = useState<Tab>("waiting");
  const { role } = useAuth();
  const actions = useActions(tab === "waiting" ? "proposed" : "all");
  const items = (actions.data ?? []).filter((a) =>
    tab === "waiting" ? a.status === "proposed" : a.status !== "proposed",
  );
  const sensitiveWaiting = tab === "waiting" && items.some((a) => a.risk === "sensitive");
  const isAgent = role === "agent";

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Approvals"
        description="Refunds, cancellations and escalations the assistant proposed while drafting replies. Nothing runs until a person approves it."
      />

      <div role="tablist" aria-label="Approvals" className="flex w-fit gap-1 rounded-[8px] border border-line bg-carbon p-1">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            type="button"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={cn(
              "rounded-[6px] px-3 py-1.5 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ion",
              tab === t.id ? "bg-carbon-elevated text-bone" : "text-ash hover:text-bone",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {actions.isPending && (
        <div aria-busy="true" aria-label="Loading actions" className="flex flex-col gap-3">
          <Skeleton className="h-36 w-full rounded-panel" />
          <Skeleton className="h-36 w-full rounded-panel" />
        </div>
      )}

      {actions.isError && <FormError>{errorMessage(actions.error)}</FormError>}

      {actions.isSuccess && items.length === 0 && tab === "waiting" && (
        <EmptyState
          illustration="approvals"
          title="Nothing waiting for approval"
          action={
            <Button asChild variant="secondary">
              <Link href="/tickets">Open the inbox</Link>
            </Button>
          }
        >
          When the assistant drafts a reply and decides a refund, a cancellation or an escalation is
          needed, it proposes the action instead of doing it. Every proposal lands here with the
          customer, the order, the amount and the assistant&apos;s reasoning, and nothing happens
          until a person approves it.
        </EmptyState>
      )}

      {actions.isSuccess && items.length === 0 && tab === "history" && (
        <p className="text-sm text-ash">No decisions yet. Approved and rejected actions show up here.</p>
      )}

      {items.length > 0 && (
        <>
          {tab === "waiting" && (
            <p
              role="note"
              className="flex items-start gap-2 rounded-[6px] border border-line bg-carbon px-3 py-2 text-sm text-ash"
            >
              <Info className="mt-0.5 size-4 shrink-0 text-ion" aria-hidden />
              <span>
                {items.length === 1 ? "1 action is" : `${items.length} actions are`} waiting.
                {isAgent && sensitiveWaiting
                  ? " Refunds and cancellations need an owner or admin; you can review them and open the ticket."
                  : " Approved actions run once, exactly as shown, and the result is added to the ticket."}
              </span>
            </p>
          )}
          <ul className="flex flex-col gap-3" aria-label={tab === "waiting" ? "Waiting actions" : "Decided actions"}>
            {items.map((a) => (
              <li key={a.id}>
                <ActionCard action={a} ticket={{ id: a.ticket_id, subject: a.ticket_subject }} />
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
