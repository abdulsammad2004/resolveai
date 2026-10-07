import { MessagesSquare } from "lucide-react";
import type { Metadata } from "next";

import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";

export const metadata: Metadata = { title: "Conversations" };

export default function ConversationsPage() {
  return (
    <div className="flex flex-col gap-4">
      <PageHeader title="Conversations" />
      <EmptyState icon={MessagesSquare} title="No conversations yet">
        Once ticket intake ships, each customer thread will appear here with their messages, your
        replies and the AI drafts side by side.
      </EmptyState>
    </div>
  );
}
