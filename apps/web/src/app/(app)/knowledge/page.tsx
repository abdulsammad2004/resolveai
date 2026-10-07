import type { Metadata } from "next";

import { KnowledgeView } from "@/components/knowledge/knowledge-view";
import { PageHeader } from "@/components/page-header";

export const metadata: Metadata = { title: "Knowledge" };

export default function KnowledgePage() {
  return (
    <div className="flex flex-col gap-4">
      <PageHeader title="Knowledge" />
      <KnowledgeView />
    </div>
  );
}
