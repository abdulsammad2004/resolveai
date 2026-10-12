import { BookOpen, Package, ReceiptText, UsersRound, Wrench, type LucideIcon } from "lucide-react";

import type { ToolCallRecord } from "@/lib/api/queries";
import { cn } from "@/lib/utils";

const timeFormat = new Intl.DateTimeFormat(undefined, { timeStyle: "short" });

const ICONS: Record<string, LucideIcon> = {
  get_order_status: Package,
  search_knowledge: BookOpen,
  request_refund: ReceiptText,
  escalate_to_human: UsersRound,
};

const STATUS_NOTE: Partial<Record<ToolCallRecord["status"], string>> = {
  invalid: "Rejected by validation",
  denied: "Not allowed",
  error: "Failed",
};

/** "What the AI checked": every tool call for this ticket and its chat, oldest first. */
export function ToolActivity({ calls }: { calls: ToolCallRecord[] }) {
  if (calls.length === 0) return null;
  return (
    <section aria-labelledby="tool-activity" className="flex flex-col gap-2">
      <h3 id="tool-activity" className="text-sm font-semibold text-bone">
        What the AI checked
      </h3>
      <ol className="flex flex-col divide-y divide-line rounded-panel border border-line">
        {calls.map((c) => {
          const Icon = ICONS[c.tool_name] ?? Wrench;
          const problem = c.status === "invalid" || c.status === "denied" || c.status === "error";
          return (
            <li key={c.id} className="flex items-start gap-3 px-3 py-2.5 text-sm">
              <Icon
                className={cn("mt-0.5 size-4 shrink-0", problem ? "text-urgent" : "text-ash")}
                aria-hidden
              />
              <div className="min-w-0 flex-1">
                <p className="break-words text-bone/90">{c.result_summary}</p>
                {STATUS_NOTE[c.status] && (
                  <p className="text-xs text-urgent">{STATUS_NOTE[c.status]}</p>
                )}
              </div>
              <time dateTime={c.created_at} className="shrink-0 text-xs text-ash tabular-nums">
                {timeFormat.format(new Date(c.created_at))}
              </time>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
