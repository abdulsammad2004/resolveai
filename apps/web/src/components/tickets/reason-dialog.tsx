"use client";

import { useId, useState, type ReactNode } from "react";

import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

const MIN_REASON = 3;
const MAX_REASON = 500;

/**
 * Asks for a reason before rejecting something. With `required`, the confirm button stays
 * disabled until there are at least a few characters.
 */
export function ReasonDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  required = false,
  pending,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: ReactNode;
  confirmLabel: string;
  required?: boolean;
  pending: boolean;
  onConfirm: (reason: string) => void;
}) {
  const [reason, setReason] = useState("");
  const [wasOpen, setWasOpen] = useState(open);
  // Start empty each time the dialog opens, however it was closed last time.
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) setReason("");
  }
  const fieldId = useId();
  const trimmed = reason.trim();
  const valid = required ? trimmed.length >= MIN_REASON : true;

  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        if (!pending) onOpenChange(next);
      }}
    >
      <AlertDialogContent>
        <AlertDialogTitle>{title}</AlertDialogTitle>
        <AlertDialogDescription>{description}</AlertDialogDescription>
        <form
          className="flex flex-col gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (valid && !pending) onConfirm(trimmed);
          }}
        >
          <label htmlFor={fieldId} className="text-xs text-ash">
            Reason{required ? "" : " (optional)"}
          </label>
          <Textarea
            id={fieldId}
            value={reason}
            maxLength={MAX_REASON}
            required={required}
            onChange={(e) => setReason(e.target.value)}
            rows={3}
            autoFocus
          />
          {required && (
            <p className="text-xs text-ash">At least {MIN_REASON} characters. Saved in the audit log.</p>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={pending}>Cancel</AlertDialogCancel>
            <Button type="submit" variant="destructive" disabled={!valid || pending}>
              {pending ? "Rejecting…" : confirmLabel}
            </Button>
          </AlertDialogFooter>
        </form>
      </AlertDialogContent>
    </AlertDialog>
  );
}
