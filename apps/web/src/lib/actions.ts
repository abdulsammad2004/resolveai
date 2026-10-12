/*
 * Plain-language copy for AI tools and the actions they propose. Shared by the Inbox
 * ticket panel and the Approvals page so both describe an action the same way.
 */

import type { ChipTone } from "@/components/status-chip";
import type { ActionStatus, ProposedAction } from "@/lib/api/queries";

const TOOL_LABELS: Record<string, string> = {
  request_refund: "Refund request",
  request_cancellation: "Order cancellation",
  escalate_to_human: "Escalation to a teammate",
  get_order_status: "Order lookup",
  search_knowledge: "Help article search",
};

export function toolLabel(name: string): string {
  if (TOOL_LABELS[name]) return TOOL_LABELS[name];
  const words = name.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export const riskLabel: Record<ProposedAction["risk"], string> = {
  sensitive: "Sensitive",
  write: "Changes data",
};

export const riskTone: Record<ProposedAction["risk"], ChipTone> = {
  sensitive: "urgent",
  write: "review",
};

export const actionStatusLabel: Record<ActionStatus, string> = {
  proposed: "Waiting for approval",
  approved: "Approved",
  rejected: "Rejected",
  executing: "Running",
  succeeded: "Done",
  failed: "Failed",
};

export const actionStatusTone: Record<ActionStatus, ChipTone> = {
  proposed: "review",
  approved: "ion",
  rejected: "neutral",
  executing: "ion",
  succeeded: "resolved",
  failed: "urgent",
};

const FIELD_LABELS: Record<string, string> = {
  order_number: "Order",
  amount: "Amount",
  email: "Email",
  query: "Search",
};

/** Refunds and cancellations: only owners and admins may approve or reject them. */
export function canDecide(role: string | null, action: Pick<ProposedAction, "risk">): boolean {
  return action.risk !== "sensitive" || role === "owner" || role === "admin";
}

/**
 * The action's arguments as readable label/value pairs. The reason is shown separately,
 * and a refund without an amount means the full order.
 */
export function argumentFields(action: Pick<ProposedAction, "tool_name" | "arguments">) {
  const fields: { label: string; value: string }[] = [];
  for (const [key, raw] of Object.entries(action.arguments)) {
    if (key === "reason" || raw === null || raw === undefined || raw === "") continue;
    const value = typeof raw === "string" ? raw : JSON.stringify(raw);
    fields.push({ label: FIELD_LABELS[key] ?? toolLabel(key), value });
  }
  if (action.tool_name === "request_refund" && !("amount" in action.arguments && action.arguments.amount)) {
    fields.push({ label: "Amount", value: "Full order" });
  }
  return fields;
}
