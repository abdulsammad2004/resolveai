import { StatusChip, type ChipTone } from "@/components/status-chip";
import type { TicketIntent, TicketPriority, TicketStatus } from "@/lib/api/queries";

export const statusLabel: Record<TicketStatus, string> = {
  new: "New",
  triaged: "Triaged",
  awaiting_review: "Awaiting review",
  replied: "Replied",
  resolved: "Resolved",
};

const statusTone: Record<TicketStatus, ChipTone> = {
  new: "ion",
  triaged: "neutral",
  awaiting_review: "review",
  replied: "neutral",
  resolved: "resolved",
};

export const priorityLabel: Record<TicketPriority, string> = {
  low: "Low",
  normal: "Normal",
  high: "High",
  urgent: "Urgent",
};

const priorityTone: Record<TicketPriority, ChipTone> = {
  low: "neutral",
  normal: "neutral",
  high: "review",
  urgent: "urgent",
};

export const STATUSES = Object.keys(statusLabel) as TicketStatus[];
export const PRIORITIES = Object.keys(priorityLabel) as TicketPriority[];

export function TicketStatusChip({ status }: { status: TicketStatus }) {
  return <StatusChip tone={statusTone[status]}>{statusLabel[status]}</StatusChip>;
}

export function PriorityChip({ priority }: { priority: TicketPriority }) {
  return (
    <StatusChip tone={priorityTone[priority]} dot={priority === "urgent"}>
      {priorityLabel[priority]}
    </StatusChip>
  );
}

// Every intent the classifier can return has an explicit label (the compiler checks this).
export const intentLabels: Record<TicketIntent, string> = {
  greeting: "Greeting",
  thanks: "Thanks",
  knowledge_question: "Knowledge question",
  order_status: "Order status",
  refund_request: "Refund request",
  cancel_order: "Cancel order",
  complaint: "Complaint",
  account_change: "Account change",
  account_security: "Account security",
  off_topic: "Off-topic",
  other: "Other",
};

/** "cancel_order" -> "Cancel order"; unknown values are humanised. */
export function intentText(intent: string): string {
  if (intent in intentLabels) return intentLabels[intent as TicketIntent];
  const words = intent.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function IntentChip({ intent }: { intent: string }) {
  return <StatusChip>{intentText(intent)}</StatusChip>;
}
