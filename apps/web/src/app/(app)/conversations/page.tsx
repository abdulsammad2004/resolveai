import type { Metadata } from "next";

import { ConversationsView } from "@/components/conversations/conversations-view";

export const metadata: Metadata = { title: "Conversations" };

export default function ConversationsPage() {
  return <ConversationsView />;
}
