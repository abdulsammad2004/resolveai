"use client";

import { FileText } from "lucide-react";

import { FormError } from "@/components/auth/form-error";
import { EmptyState } from "@/components/empty-state";
import { GlassPanel } from "@/components/glass-panel";
import { StatusChip, type ChipTone } from "@/components/status-chip";
import { Skeleton } from "@/components/ui/skeleton";
import { errorMessage } from "@/lib/api/errors";
import { useDocuments, type DocumentItem } from "@/lib/api/queries";

const statusLabel: Record<DocumentItem["status"], string> = {
  uploaded: "Uploaded",
  processing: "Processing",
  ready: "Ready",
  failed: "Failed",
};

const statusTone: Record<DocumentItem["status"], ChipTone> = {
  uploaded: "neutral",
  processing: "review",
  ready: "resolved",
  failed: "urgent",
};

export function KnowledgeView() {
  const documents = useDocuments();

  if (documents.isPending) {
    return (
      <GlassPanel aria-busy="true" aria-label="Loading documents" className="flex flex-col gap-4">
        {[0, 1, 2].map((i) => (
          <div key={i} className="flex items-center gap-3">
            <Skeleton className="size-9 shrink-0" />
            <div className="flex flex-1 flex-col gap-2">
              <Skeleton className="h-3.5 w-1/2" />
              <Skeleton className="h-3 w-1/4" />
            </div>
            <Skeleton className="h-6 w-16" />
          </div>
        ))}
      </GlassPanel>
    );
  }

  if (documents.isError) {
    return (
      <GlassPanel>
        <FormError>{errorMessage(documents.error)}</FormError>
      </GlassPanel>
    );
  }

  if (documents.data.length === 0) {
    return (
      <EmptyState illustration="knowledge" title="No documents yet">
        Add help articles and policies here, and the assistant will cite them in every draft it
        writes.
      </EmptyState>
    );
  }

  return (
    <GlassPanel aria-label="Documents">
      <ul className="flex flex-col divide-y divide-line">
        {documents.data.map((doc) => (
          <li key={doc.id} className="flex items-center gap-3 py-3.5">
            <span className="grid size-9 shrink-0 place-items-center rounded-[6px] border border-line bg-carbon-elevated text-ash">
              <FileText className="size-4" aria-hidden />
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold text-bone">{doc.title}</p>
              <p className="truncate text-xs text-ash">
                {doc.filename}
                {doc.status === "ready" && ` · ${doc.chunk_count} ${doc.chunk_count === 1 ? "chunk" : "chunks"}`}
              </p>
            </div>
            <StatusChip tone={statusTone[doc.status]}>{statusLabel[doc.status]}</StatusChip>
          </li>
        ))}
      </ul>
    </GlassPanel>
  );
}
