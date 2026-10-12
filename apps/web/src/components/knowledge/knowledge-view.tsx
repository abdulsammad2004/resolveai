"use client";

import { FileText, Loader2, RotateCw, Trash2 } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useId, useState } from "react";
import { toast } from "sonner";

import { FormError } from "@/components/auth/form-error";
import { EmptyIllustration } from "@/components/empty-illustration";
import { GlassPanel } from "@/components/glass-panel";
import { SearchPanel } from "@/components/knowledge/search-panel";
import { UploadZone } from "@/components/knowledge/upload-zone";
import { PageHeader } from "@/components/page-header";
import { StatusChip, type ChipTone } from "@/components/status-chip";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { errorMessage } from "@/lib/api/errors";
import {
  useDeleteDocument,
  useDocuments,
  useReindexDocument,
  type DocumentItem,
  type DocumentStatus,
} from "@/lib/api/queries";
import { useAuth } from "@/lib/auth/auth-provider";

const statusLabel: Record<DocumentStatus, string> = {
  uploaded: "Uploaded",
  processing: "Processing",
  ready: "Ready",
  failed: "Failed",
};

const statusTone: Record<DocumentStatus, ChipTone> = {
  uploaded: "neutral",
  processing: "review",
  ready: "resolved",
  failed: "urgent",
};

const typeLabel: Record<string, string> = {
  "application/pdf": "PDF",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "DOCX",
  "text/plain": "TXT",
  "text/markdown": "Markdown",
};

function fileType(doc: DocumentItem): string {
  return typeLabel[doc.mime_type] ?? doc.filename.split(".").pop()?.toUpperCase() ?? "File";
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });

export function KnowledgeView() {
  const { role, workspace } = useAuth();
  const documents = useDocuments();
  const canEdit = role === "owner" || role === "admin";
  const readyCount = documents.data?.filter((d) => d.status === "ready").length ?? 0;

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-6">
      <PageHeader
        title="Knowledge"
        description={
          documents.isPending ? (
            <Skeleton className="h-5 w-48" />
          ) : documents.data ? (
            <p aria-live="polite">
              <span className="font-semibold text-bone tabular-nums">{readyCount}</span>{" "}
              {readyCount === 1 ? "document" : "documents"} ready for the assistant to cite
            </p>
          ) : null
        }
      />

      {documents.isPending && <ListSkeleton />}

      {documents.isError && (
        <GlassPanel>
          <FormError>{errorMessage(documents.error)}</FormError>
        </GlassPanel>
      )}

      {documents.data?.length === 0 && <EmptyKnowledge />}

      {documents.data && documents.data.length > 0 && (
        <div className="grid items-start gap-6 lg:grid-cols-5">
          <div className="flex min-w-0 flex-col gap-4 lg:col-span-3">
            <UploadZone />
            <DocumentList documents={documents.data} canEdit={canEdit} />
          </div>
          <div className="min-w-0 lg:sticky lg:top-6 lg:col-span-2">
            {/* Keyed so results never carry over after a workspace switch. */}
            <SearchPanel key={workspace?.id} readyCount={readyCount} />
          </div>
        </div>
      )}
    </div>
  );
}

function ListSkeleton() {
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

function EmptyKnowledge() {
  return (
    <GlassPanel className="flex flex-col items-center gap-6 p-6 text-center sm:p-10">
      <EmptyIllustration kind="knowledge" className="size-20 sm:size-24" />
      <div className="flex max-w-xl flex-col gap-2">
        <h2 className="font-display text-3xl font-bold tracking-tight text-bone sm:text-4xl">
          Teach the assistant your business
        </h2>
        <p className="text-base leading-relaxed text-ash">
          Add help articles, policies and FAQs. The assistant answers only from these documents
          and cites the passage it used, so agents can check every draft.
        </p>
      </div>
      <div className="w-full max-w-2xl text-left">
        <UploadZone size="hero" />
      </div>
    </GlassPanel>
  );
}

function DocumentList({ documents, canEdit }: { documents: DocumentItem[]; canEdit: boolean }) {
  const still = useReducedMotion() ?? false;
  const [pendingDelete, setPendingDelete] = useState<DocumentItem | null>(null);
  const remove = useDeleteDocument();

  async function confirmDelete() {
    if (!pendingDelete) return;
    const doc = pendingDelete;
    try {
      await remove.mutateAsync(doc.id);
      toast.success(`Deleted “${doc.title}”.`);
      setPendingDelete(null);
    } catch (err) {
      toast.error(errorMessage(err));
    }
  }

  return (
    <GlassPanel aria-labelledby="documents-title" className="p-5 sm:p-6">
      <h2 id="documents-title" className="mb-1 text-lg font-semibold text-bone">
        Documents
      </h2>
      <ul className="flex flex-col divide-y divide-line">
        <AnimatePresence initial={false}>
          {documents.map((doc) => (
            <motion.li
              key={doc.id}
              layout={!still}
              initial={still ? false : { opacity: 0, y: -6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={still ? { opacity: 0, transition: { duration: 0 } } : { opacity: 0, x: 12 }}
              transition={{ duration: 0.18, ease: "easeOut" }}
            >
              <DocumentRow doc={doc} canEdit={canEdit} onDelete={() => setPendingDelete(doc)} />
            </motion.li>
          ))}
        </AnimatePresence>
      </ul>

      <AlertDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open && !remove.isPending) setPendingDelete(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogTitle>Delete this document?</AlertDialogTitle>
          <AlertDialogDescription>
            “{pendingDelete?.title}” and all of its indexed passages will be removed. The assistant
            will stop citing it straight away. This can&apos;t be undone.
          </AlertDialogDescription>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={remove.isPending}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={remove.isPending}
              onClick={(e) => {
                // Keep the dialog open until the delete has finished.
                e.preventDefault();
                void confirmDelete();
              }}
            >
              {remove.isPending ? "Deleting…" : "Delete document"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </GlassPanel>
  );
}

function DocumentRow({
  doc,
  canEdit,
  onDelete,
}: {
  doc: DocumentItem;
  canEdit: boolean;
  onDelete: () => void;
}) {
  const reindex = useReindexDocument();
  const settling = doc.status === "uploaded" || doc.status === "processing";

  async function onReindex() {
    try {
      await reindex.mutateAsync(doc.id);
      toast.success(`Reindexing “${doc.title}”.`);
    } catch (err) {
      toast.error(errorMessage(err));
    }
  }

  return (
    <div className="flex flex-col gap-3 py-3.5 sm:flex-row sm:items-center">
      <div className="flex min-w-0 flex-1 items-center gap-3">
        <span className="grid size-9 shrink-0 place-items-center rounded-[6px] border border-line bg-carbon-elevated text-ash">
          <FileText className="size-4" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-bone" title={doc.title}>
            {doc.title}
          </p>
          <p className="truncate text-xs text-ash">
            {fileType(doc)} · {formatSize(doc.size_bytes)} ·{" "}
            <time dateTime={doc.created_at}>{dateFormat.format(new Date(doc.created_at))}</time>
            {doc.status === "ready" &&
              ` · ${doc.chunk_count} ${doc.chunk_count === 1 ? "passage" : "passages"}`}
          </p>
        </div>
      </div>

      <div className="flex items-center justify-between gap-2 pl-12 sm:justify-end sm:pl-0">
        <DocumentStatusChip doc={doc} />
        {canEdit && (
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="icon"
              className="size-8"
              onClick={onReindex}
              disabled={settling || reindex.isPending}
              aria-label={`Reindex ${doc.title}`}
              title="Reindex"
            >
              <RotateCw className={reindex.isPending ? "motion-safe:animate-spin" : undefined} aria-hidden />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="size-8 hover:text-urgent"
              onClick={onDelete}
              aria-label={`Delete ${doc.title}`}
              title="Delete"
            >
              <Trash2 aria-hidden />
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

function DocumentStatusChip({ doc }: { doc: DocumentItem }) {
  const tooltipId = useId();
  const chip = (
    <StatusChip tone={statusTone[doc.status]}>
      {doc.status === "processing" && (
        <Loader2 className="size-3 motion-safe:animate-spin" aria-hidden />
      )}
      {statusLabel[doc.status]}
    </StatusChip>
  );

  if (doc.status !== "failed" || !doc.error) return chip;

  // Focusable so the error is reachable by keyboard and by tap on touch screens.
  return (
    <span className="group relative inline-flex">
      <button
        type="button"
        aria-describedby={tooltipId}
        className="rounded-[4px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ion"
      >
        {chip}
      </button>
      <span
        id={tooltipId}
        role="tooltip"
        className="pointer-events-none invisible absolute right-0 bottom-full z-20 mb-2 w-64 max-w-[calc(100vw-2rem)] rounded-[6px] border border-line-strong bg-carbon-elevated px-3 py-2 text-xs leading-relaxed text-bone opacity-0 shadow-xl transition-opacity group-focus-within:visible group-focus-within:opacity-100 group-hover:visible group-hover:opacity-100 sm:right-auto sm:left-1/2 sm:-translate-x-1/2"
      >
        {doc.error}
      </span>
    </span>
  );
}
