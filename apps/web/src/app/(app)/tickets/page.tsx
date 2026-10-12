import type { Metadata } from "next";
import { Suspense } from "react";

import { TicketsView } from "@/components/tickets/tickets-view";

export const metadata: Metadata = { title: "Inbox" };

// `?ticket=<id>` opens that ticket (links from Approvals). Search params are runtime data,
// so they are read inside a Suspense boundary.
export default function TicketsPage({ searchParams }: PageProps<"/tickets">) {
  return (
    <Suspense fallback={<TicketsView />}>
      {searchParams.then(({ ticket }) => (
        <TicketsView initialTicketId={typeof ticket === "string" ? ticket : null} />
      ))}
    </Suspense>
  );
}
