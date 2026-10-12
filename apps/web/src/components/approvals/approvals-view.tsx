"use client";

import { Info } from "lucide-react";
import Link from "next/link";

import { FormError } from "@/components/auth/form-error";
import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { ActionCard } from "@/components/tickets/proposed-actions";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { errorMessage } from "@/lib/api/errors";
import { useActions } from "@/lib/api/queries";

export function ApprovalsView() {
  const actions = useActions("proposed");
  const items = actions.data ?? [];

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Approvals"
        description="Refunds and escalations the assistant proposed while drafting replies. Nothing here has been carried out."
      />

      {actions.isPending && (
        <div aria-busy="true" aria-label="Loading proposed actions" className="flex flex-col gap-3">
          <Skeleton className="h-36 w-full rounded-panel" />
          <Skeleton className="h-36 w-full rounded-panel" />
        </div>
      )}

      {actions.isError && <FormError>{errorMessage(actions.error)}</FormError>}

      {actions.isSuccess && items.length === 0 && (
        <EmptyState
          illustration="approvals"
          title="Nothing waiting for approval"
          action={
            <Button asChild variant="secondary">
              <Link href="/tickets">Open the inbox</Link>
            </Button>
          }
        >
          When the assistant drafts a reply and decides a refund or an escalation is needed, it
          proposes the action instead of doing it. Every proposal lands here with the order, the
          amount and the assistant&apos;s reasoning, and nothing happens until a person approves
          it.
        </EmptyState>
      )}

      {items.length > 0 && (
        <>
          <p
            role="note"
            className="flex items-start gap-2 rounded-[6px] border border-line bg-carbon px-3 py-2 text-sm text-ash"
          >
            <Info className="mt-0.5 size-4 shrink-0 text-ion" aria-hidden />
            <span>
              {items.length === 1 ? "1 action is" : `${items.length} actions are`} waiting. Approving
              and rejecting arrive in the next update; for now, open the ticket to review the
              context.
            </span>
          </p>
          <ul className="flex flex-col gap-3" aria-label="Proposed actions">
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
