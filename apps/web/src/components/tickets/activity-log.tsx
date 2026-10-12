import { History } from "lucide-react";

import { statusLabel, priorityLabel } from "@/components/tickets/ticket-chips";
import { toolLabel } from "@/lib/actions";
import type { AuditEvent, TicketPriority, TicketStatus } from "@/lib/api/queries";
import { cn } from "@/lib/utils";

const timeFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

type Summary = Record<string, unknown> | null | undefined;

function field(summary: Summary, key: string): string | undefined {
  const value = summary?.[key];
  return typeof value === "string" ? value : undefined;
}

function actorName(e: AuditEvent): string {
  if (e.actor_type === "ai") return "The AI";
  if (e.actor_type === "system") return "ResolveAI";
  if (e.actor_type === "customer") return "The customer";
  return e.actor_name ?? "A teammate";
}

function statusText(value: string | undefined): string {
  return value ? (statusLabel[value as TicketStatus] ?? value).toLowerCase() : "unknown";
}

/** One audit event as a plain sentence, plus an optional detail line. */
function describe(e: AuditEvent): { text: string; detail?: string; tone?: "good" | "bad" } {
  const who = actorName(e);
  const tool = toolLabel(field(e.after, "tool_name") ?? "action").toLowerCase();
  switch (e.action) {
    case "draft.created":
      return { text: `${who} started writing a reply` };
    case "draft.edited":
      return { text: `${who} edited the draft` };
    case "draft.approved":
      return { text: `${who} approved the AI draft` };
    case "draft.sent": {
      const how =
        e.after?.author_type === "human"
          ? "their own reply"
          : e.after?.edited
            ? "an edited AI draft"
            : "the AI draft";
      return { text: `${who} sent ${how} to the customer`, tone: "good" };
    }
    case "draft.rejected":
      return { text: `${who} rejected the draft`, detail: field(e.after, "reason") };
    case "action.proposed":
      return { text: `${who} proposed a ${tool}` };
    case "action.approved":
      return { text: `${who} approved the ${tool}` };
    case "action.rejected":
      return { text: `${who} rejected the ${tool}`, detail: field(e.after, "reason") };
    case "action.executed":
      return { text: field(e.after, "summary") ?? `The ${tool} was carried out`, tone: "good" };
    case "action.failed":
      return { text: `The ${tool} failed`, detail: field(e.after, "summary"), tone: "bad" };
    case "ticket.status_changed": {
      const from = field(e.before, "status");
      const to = field(e.after, "status");
      if (e.actor_type === "customer" && to === "awaiting_review") {
        return { text: "The customer reopened the resolved ticket (“Still need help?”)" };
      }
      if (e.actor_type === "system" && to === "awaiting_review") {
        return { text: `Reopened: the customer wrote again (was ${statusText(from)})` };
      }
      return { text: `${who} moved the ticket from ${statusText(from)} to ${statusText(to)}` };
    }
    case "ticket.priority_changed": {
      const to = field(e.after, "priority") as TicketPriority | undefined;
      return { text: `${who} set the priority to ${to ? priorityLabel[to].toLowerCase() : "unknown"}` };
    }
    case "ticket.assignee_changed":
      return { text: field(e.after, "assignee_id") ? `${who} changed the assignee` : `${who} unassigned the ticket` };
    case "conversation.closed":
      return { text: "The chat was closed; new messages from the customer start a new chat" };
    case "conversation.reopened":
      return { text: "The chat was reopened and is with the team again" };
    case "ticket.resolution_rated": {
      const rating = field(e.after, "rating");
      return {
        text: `The customer rated the resolution ${rating === "up" ? "helpful" : "not helpful"}`,
        tone: rating === "up" ? "good" : "bad",
      };
    }
    default:
      return { text: `${who}: ${e.action}` };
  }
}

/** The ticket's audit trail, oldest first. */
export function ActivityLog({ events }: { events: AuditEvent[] }) {
  return (
    <section aria-labelledby="ticket-activity" className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <History className="size-4 text-ash" aria-hidden />
        <h3 id="ticket-activity" className="text-sm font-semibold text-bone">
          Activity
        </h3>
      </div>
      {events.length === 0 ? (
        <p className="text-sm text-ash">No reviews, decisions or changes yet.</p>
      ) : (
        <ol className="flex flex-col gap-2 border-l border-line pl-4" aria-label="Activity">
          {events.map((e) => {
            const d = describe(e);
            return (
              <li key={e.id} className="relative flex flex-col gap-0.5">
                <span
                  aria-hidden
                  className={cn(
                    "absolute top-1.5 -left-[21px] size-2 rounded-full border border-ink",
                    d.tone === "good" ? "bg-resolved" : d.tone === "bad" ? "bg-urgent" : "bg-ash/60",
                  )}
                />
                <span className="text-sm text-bone/90">{d.text}</span>
                {d.detail && <span className="text-xs text-bone/70">“{d.detail}”</span>}
                <time dateTime={e.created_at} className="text-[11px] text-ash">
                  {timeFormat.format(new Date(e.created_at))}
                </time>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
