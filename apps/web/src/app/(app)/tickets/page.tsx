import type { Metadata } from "next";

import { TicketsView } from "@/components/tickets/tickets-view";

export const metadata: Metadata = { title: "Inbox" };

export default function TicketsPage() {
  return <TicketsView />;
}
