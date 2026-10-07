import type { Metadata } from "next";

import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";

export const metadata: Metadata = { title: "Approvals" };

export default function ApprovalsPage() {
  return (
    <div className="flex flex-col gap-4">
      <PageHeader title="Approvals" />
      <EmptyState illustration="approvals" title="Nothing to approve">
        When tool actions switch on after ticket intake, refunds and account changes the assistant
        proposes will wait here until an admin approves or rejects them.
      </EmptyState>
    </div>
  );
}
