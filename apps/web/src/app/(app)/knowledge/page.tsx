import { BookOpen } from "lucide-react";
import type { Metadata } from "next";

import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";

export const metadata: Metadata = { title: "Knowledge" };

export default function KnowledgePage() {
  return (
    <div className="flex flex-col gap-4">
      <PageHeader title="Knowledge" />
      <EmptyState icon={BookOpen} title="No documents yet">
        Document upload is the next feature we&apos;re building: you&apos;ll add help articles and
        policies here, and the assistant will cite them in every draft it writes.
      </EmptyState>
    </div>
  );
}
