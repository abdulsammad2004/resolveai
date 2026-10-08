import type { Metadata } from "next";

import { KnowledgeView } from "@/components/knowledge/knowledge-view";

export const metadata: Metadata = { title: "Knowledge" };

// The view renders its own header: the ready-document count comes from live data.
export default function KnowledgePage() {
  return <KnowledgeView />;
}
