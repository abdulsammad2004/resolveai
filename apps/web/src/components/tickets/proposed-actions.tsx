import { ShieldAlert } from "lucide-react";
import Link from "next/link";

import { StatusChip } from "@/components/status-chip";
import {
  actionStatusLabel,
  actionStatusTone,
  argumentFields,
  riskLabel,
  riskTone,
  toolLabel,
} from "@/lib/actions";
import type { ProposedAction } from "@/lib/api/queries";
import { cn } from "@/lib/utils";

const timeFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

/** One action the AI proposed: what, how risky, with which arguments, and why. */
export function ActionCard({
  action,
  ticket,
}: {
  action: ProposedAction;
  /** Shown on the Approvals page: the ticket the action belongs to. */
  ticket?: { id: string; subject: string };
}) {
  const fields = argumentFields(action);
  return (
    <article
      aria-label={toolLabel(action.tool_name)}
      className={cn(
        "flex flex-col gap-3 rounded-panel border bg-carbon-input p-4",
        action.risk === "sensitive" ? "border-urgent/25" : "border-line",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="text-sm font-semibold text-bone">{toolLabel(action.tool_name)}</h4>
        <StatusChip tone={riskTone[action.risk]}>{riskLabel[action.risk]}</StatusChip>
        <StatusChip tone={actionStatusTone[action.status]} dot={action.status === "proposed"}>
          {actionStatusLabel[action.status]}
        </StatusChip>
        <span className="ml-auto text-xs text-ash">{timeFormat.format(new Date(action.created_at))}</span>
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
    </article>
  );
}

export function ProposedActions({ actions }: { actions: ProposedAction[] }) {
  if (actions.length === 0) return null;
  return (
    <section aria-labelledby="proposed-actions" className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <ShieldAlert className="size-4 text-review" aria-hidden />
        <h3 id="proposed-actions" className="text-sm font-semibold text-bone">
          Proposed actions
        </h3>
      </div>
      <p className="text-xs text-ash">
        Nothing here has been done. Each action waits for a person to approve it.
      </p>
      <div className="flex flex-col gap-2">
        {actions.map((a) => (
          <ActionCard key={a.id} action={a} />
        ))}
      </div>
    </section>
  );
}
