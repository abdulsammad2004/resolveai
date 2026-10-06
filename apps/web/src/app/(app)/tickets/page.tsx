import { Inbox } from "lucide-react";
import type { Metadata } from "next";

import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";

export const metadata: Metadata = { title: "Inbox" };

export default function TicketsPage() {
  return (
    <div className="flex flex-col gap-4">
      <PageHeader title="Inbox" />
      <EmptyState icon={Inbox} title="No tickets yet">
        Once ticket intake ships, the next milestone after the knowledge base, every message from
        your chat widget will arrive here as a ticket, already classified and prioritised.
      </EmptyState>
    </div>
  );
}
