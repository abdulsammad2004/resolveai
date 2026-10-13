"use client";

import { Check, CircleAlert, CircleCheck, ShieldAlert, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { StatusChip } from "@/components/status-chip";
import { ReasonDialog } from "@/components/tickets/reason-dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import {
  actionStatusLabel,
  actionStatusTone,
  argumentFields,
  canDecide,
  riskLabel,
  riskTone,
  toolLabel,
} from "@/lib/actions";
import { errorMessage } from "@/lib/api/errors";
import {
  isActionRunning,
  useApproveAction,
  useRejectAction,
  type ActionListItem,
  type ProposedAction,
} from "@/lib/api/queries";
import { useAuth } from "@/lib/auth/auth-provider";
import { cn } from "@/lib/utils";

const timeFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

function isListItem(action: ProposedAction | ActionListItem): action is ActionListItem {
  return "ticket_subject" in action;
}

/** Label/value rows: the customer and order (Approvals page), then the action's arguments. */
function detailFields(action: ProposedAction | ActionListItem) {
  const fields = argumentFields(action);
  if (!isListItem(action)) return fields;
  const rows: { label: string; value: string }[] = [];
  if (action.contact) {
    const name = action.contact.name || action.contact.email || "Website visitor";
    const email = action.contact.email && action.contact.email !== name ? ` · ${action.contact.email}` : "";
    rows.push({ label: "Customer", value: `${name}${email}` });
  }
  for (const f of fields) {
    // A refund without an amount is the full order: show what that comes to.
    if (f.label === "Amount" && f.value === "Full order" && action.amount) {
      rows.push({ label: "Amount", value: `${action.amount} (full order)` });
    } else {
      rows.push(f);
    }
  }
  return rows;
}

/** One action the AI proposed: what, how risky, with which arguments, why, and its outcome. */
export function ActionCard({
  action,
  ticket,
}: {
  action: ProposedAction | ActionListItem;
  /** Shown on the Approvals page: the ticket the action belongs to. */
  ticket?: { id: string; subject: string };
}) {
  const { role } = useAuth();
  const approve = useApproveAction();
  const reject = useRejectAction();
  const [confirming, setConfirming] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const fields = detailFields(action);
  const allowed = canDecide(role, action);
  const label = toolLabel(action.tool_name);
  const result = action.result as { ok?: boolean; summary?: string } | null | undefined;

  async function doApprove() {
    try {
      await approve.mutateAsync(action.id);
      setConfirming(false);
      toast.success(`${label} approved. Carrying it out now.`);
    } catch (error) {
      toast.error(errorMessage(error));
    }
  }

  async function doReject(reason: string) {
    try {
      await reject.mutateAsync({ actionId: action.id, reason });
      setRejecting(false);
      toast.success(`${label} rejected.`);
    } catch (error) {
      toast.error(errorMessage(error));
    }
  }

  return (
    <article
      aria-label={label}
      className={cn(
        "flex flex-col gap-3 rounded-panel border bg-carbon-input p-4",
        action.risk === "sensitive" ? "border-urgent/25" : "border-line",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="text-sm font-semibold text-bone">{label}</h4>
        <StatusChip tone={riskTone[action.risk]}>{riskLabel[action.risk]}</StatusChip>
        <StatusChip
          tone={actionStatusTone[action.status]}
          dot={action.status === "proposed" || isActionRunning(action)}
        >
          {actionStatusLabel[action.status]}
        </StatusChip>
        <span className="ml-auto text-xs text-ash">
          Proposed by the AI · {timeFormat.format(new Date(action.created_at))}
        </span>
      </div>

      {ticket && (
        <Link
          href={`/tickets?ticket=${ticket.id}`}
          className="w-fit max-w-full truncate text-sm text-ion underline-offset-4 hover:underline focus-visible:rounded-[4px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ion"
        >
          {ticket.subject}
        </Link>
      )}

      {fields.length > 0 && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
          {fields.map((f) => (
            <div key={f.label} className="contents">
              <dt className="text-ash">{f.label}</dt>
              <dd className="min-w-0 break-words text-bone">{f.value}</dd>
            </div>
          ))}
        </dl>
      )}

      {action.reason && (
        <div className="flex flex-col gap-1">
          <span className="text-xs text-ash">Why the AI proposed it</span>
          <p className="text-sm leading-relaxed whitespace-pre-wrap text-bone/90">{action.reason}</p>
        </div>
      )}

      {action.status !== "proposed" && action.decided_at && (
        <p className="text-xs text-ash">
          {action.status === "rejected" ? "Rejected" : "Approved"} by{" "}
          {action.decided_by_name ?? "a teammate"} · {timeFormat.format(new Date(action.decided_at))}
          {action.status === "rejected" && action.decision_reason && (
            <span className="text-bone/90"> — “{action.decision_reason}”</span>
          )}
        </p>
      )}

      {isActionRunning(action) && (
        <p role="status" className="text-sm text-ash">
          Carrying it out…
        </p>
      )}

      {result?.summary && (
        <p
          role={result.ok ? "status" : "alert"}
          className={cn(
            "flex items-start gap-2 rounded-[6px] border px-3 py-2 text-sm text-bone",
            result.ok ? "border-resolved/20 bg-resolved/10" : "border-urgent/20 bg-urgent/10",
          )}
        >
          {result.ok ? (
            <CircleCheck className="mt-0.5 size-4 shrink-0 text-resolved" aria-hidden />
          ) : (
            <CircleAlert className="mt-0.5 size-4 shrink-0 text-urgent" aria-hidden />
          )}
          <span>
            {result.summary}
            {!ticket && (
              <span className="block text-xs text-ash">
                The assistant drafts a reply telling the customer; review it in the reply panel.
              </span>
            )}
          </span>
        </p>
      )}

      {action.status === "proposed" &&
        (allowed ? (
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              onClick={() => (action.risk === "sensitive" ? setConfirming(true) : void doApprove())}
              disabled={approve.isPending || reject.isPending}
              className="gap-1.5"
            >
              <Check className="size-3.5" aria-hidden />
              {approve.isPending ? "Approving…" : "Approve"}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setRejecting(true)}
              disabled={approve.isPending || reject.isPending}
              className="gap-1.5"
            >
              <X className="size-3.5" aria-hidden />
              Reject
            </Button>
          </div>
        ) : (
          <p className="text-xs text-ash">
            Only owners and admins can approve or reject refunds and cancellations.
          </p>
        ))}

      <AlertDialog open={confirming} onOpenChange={(open) => !approve.isPending && setConfirming(open)}>
        <AlertDialogContent>
          <AlertDialogTitle>Approve this {label.toLowerCase()}?</AlertDialogTitle>
          <AlertDialogDescription>
            It will be carried out right away with exactly these details
            {fields.length > 0 && `: ${fields.map((f) => `${f.label.toLowerCase()} ${f.value}`).join(", ")}`}.
            Your approval is recorded in the audit log.
          </AlertDialogDescription>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={approve.isPending}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={approve.isPending}
              onClick={(e) => {
                // Keep the dialog open until the approval has gone through.
                e.preventDefault();
                void doApprove();
              }}
            >
              {approve.isPending ? "Approving…" : "Approve"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <ReasonDialog
        open={rejecting}
        onOpenChange={setRejecting}
        title={`Reject this ${label.toLowerCase()}?`}
        description="Nothing is carried out. The reason is saved with the decision."
        confirmLabel="Reject"
        required
        pending={reject.isPending}
        onConfirm={(reason) => void doReject(reason)}
      />
    </article>
  );
}

export function ProposedActions({ actions }: { actions: ProposedAction[] }) {
  if (actions.length === 0) return null;
  const waiting = actions.some((a) => a.status === "proposed");
  return (
    <section aria-labelledby="proposed-actions" className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <ShieldAlert className="size-4 text-review" aria-hidden />
        <h3 id="proposed-actions" className="text-sm font-semibold text-bone">
          Actions
        </h3>
      </div>
      {waiting && (
        <p className="text-xs text-ash">
          Nothing proposed here has been done. Each action waits for a person to approve it.
        </p>
      )}
      <div className="flex flex-col gap-2">
        {actions.map((a) => (
          <ActionCard key={a.id} action={a} />
        ))}
      </div>
    </section>
  );
}
