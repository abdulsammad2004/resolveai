"use client";

import { FileUp, Lock } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { useId, useRef, useState, type DragEvent } from "react";
import { toast } from "sonner";

import { errorMessage } from "@/lib/api/errors";
import { useUploadDocument } from "@/lib/api/queries";
import { useAuth } from "@/lib/auth/auth-provider";
import { cn } from "@/lib/utils";

/** Must match MAX_UPLOAD_MB and the parsers in services/api. */
export const MAX_UPLOAD_MB = 20;
const MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024;
const ACCEPTED_EXTENSIONS = [".pdf", ".docx", ".txt", ".md"] as const;

function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot === -1 ? "" : name.slice(dot).toLowerCase();
}

/** Returns a reason the file can't be uploaded, or null if it looks fine. */
function rejectReason(file: File): string | null {
  if (!(ACCEPTED_EXTENSIONS as readonly string[]).includes(extensionOf(file.name))) {
    return "Only PDF, DOCX, TXT and Markdown files can be added.";
  }
  if (file.size === 0) return "The file is empty.";
  if (file.size > MAX_UPLOAD_BYTES) return `The file is larger than ${MAX_UPLOAD_MB} MB.`;
  return null;
}

type Progress = { name: string; index: number; total: number; fraction: number };

export function UploadZone({ size = "compact" }: { size?: "compact" | "hero" }) {
  const { role } = useAuth();
  const canUpload = role === "owner" || role === "admin";
  const upload = useUploadDocument();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState<Progress | null>(null);
  const hintId = useId();
  const still = useReducedMotion() ?? false;
  const hero = size === "hero";

  if (!canUpload) {
    return (
      <p className="flex items-start gap-2.5 rounded-panel border border-line bg-carbon px-4 py-3.5 text-sm text-ash">
        <Lock className="mt-0.5 size-4 shrink-0" aria-hidden />
        Only owners and admins can add or remove documents. You can still test search on what
        is already here.
      </p>
    );
  }

  const busy = progress !== null;

  async function uploadFiles(list: FileList | File[]) {
    const files = Array.from(list);
    if (files.length === 0 || busy) return;
    const valid = files.filter((file) => {
      const reason = rejectReason(file);
      if (reason) toast.error(`${file.name}: ${reason}`);
      return !reason;
    });

    for (const [index, file] of valid.entries()) {
      setProgress({ name: file.name, index, total: valid.length, fraction: 0 });
      try {
        const doc = await upload.mutateAsync({
          file,
          onProgress: (fraction) =>
            setProgress((p) => (p && p.name === file.name ? { ...p, fraction } : p)),
        });
        toast.success(`Added “${doc.title}”. Indexing has started.`);
      } catch (err) {
        toast.error(`${file.name}: ${errorMessage(err)}`);
      }
    }
    setProgress(null);
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    void uploadFiles(event.dataTransfer.files);
  }

  function onDragOver(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    event.dataTransfer.dropEffect = busy ? "none" : "copy";
    if (!busy) setDragging(true);
  }

  // Bytes sent is not the end: the server still hashes and stores the file.
  const sent = progress !== null && progress.fraction >= 1;

  return (
    <div
      onDragOver={onDragOver}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false);
      }}
      onDrop={onDrop}
      className={cn(
        "relative overflow-hidden rounded-panel border border-dashed transition-colors",
        dragging ? "border-ion bg-ion/[0.07]" : "border-line-strong bg-carbon hover:border-ion/60",
      )}
    >
      <input
        ref={inputRef}
        type="file"
        multiple
        accept={ACCEPTED_EXTENSIONS.join(",")}
        className="sr-only"
        tabIndex={-1}
        aria-hidden
        onChange={(e) => {
          if (e.target.files) void uploadFiles(e.target.files);
          e.target.value = "";
        }}
      />

      {progress ? (
        <div
          className={cn("flex flex-col gap-3", hero ? "p-6 sm:p-10" : "p-5")}
          role="status"
          aria-live="polite"
        >
          <div className="flex items-baseline justify-between gap-3 text-sm">
            <span className="min-w-0 truncate font-medium text-bone">
              {sent ? "Saving" : "Uploading"} {progress.name}
            </span>
            <span className="shrink-0 tabular-nums text-ash">
              {progress.total > 1 && `${progress.index + 1} of ${progress.total} · `}
              {Math.round(progress.fraction * 100)}%
            </span>
          </div>
          <div
            className="relative h-1.5 overflow-hidden rounded-full bg-white/[0.08]"
            role="progressbar"
            aria-label={`Uploading ${progress.name}`}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(progress.fraction * 100)}
          >
            <motion.div
              className="h-full rounded-full bg-ion"
              initial={false}
              animate={{ width: `${Math.max(progress.fraction, 0.02) * 100}%` }}
              transition={{ duration: still ? 0 : 0.25, ease: "easeOut" }}
            />
            {sent && !still && (
              <span
                className="loader-bar absolute inset-0 bg-gradient-to-r from-transparent via-white/40 to-transparent"
                aria-hidden
              />
            )}
          </div>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          aria-describedby={hintId}
          className={cn(
            "pressable flex w-full flex-col items-center gap-3 text-center focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ion focus-visible:ring-inset",
            hero ? "px-6 py-12 sm:py-16" : "px-5 py-7",
          )}
        >
          <motion.span
            className={cn(
              "grid place-items-center rounded-[10px] border border-ion/30 bg-ion/10 text-ion",
              hero ? "size-14" : "size-11",
            )}
            animate={dragging && !still ? { y: -4, scale: 1.06 } : { y: 0, scale: 1 }}
            transition={{ type: "spring", stiffness: 400, damping: 22 }}
            aria-hidden
          >
            <FileUp className={hero ? "size-6" : "size-5"} />
          </motion.span>
          <span className={cn("font-semibold text-bone", hero ? "text-lg" : "text-sm")}>
            {dragging ? "Drop to upload" : "Drop files here or choose files"}
          </span>
          <span id={hintId} className="text-xs text-ash">
            PDF, DOCX, TXT or Markdown, up to {MAX_UPLOAD_MB} MB each
          </span>
        </button>
      )}
    </div>
  );
}
