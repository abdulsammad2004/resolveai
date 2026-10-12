"use client";

import { Trash2 } from "lucide-react";
import { useId, useState } from "react";
import { toast } from "sonner";

import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { errorMessage } from "@/lib/api/errors";
import { useDemoTools, useResetDemoData, type DemoReset } from "@/lib/api/queries";
import { useAuth } from "@/lib/auth/auth-provider";

const DELETED = [
  "Conversations, messages and widget visitors",
  "Inbox tickets, reply drafts and tool activity",
  "Proposed and decided actions (approvals)",
  "The audit log and customer ratings",
];
const KEPT = [
  "Your team, workspace settings and widget key",
  "Knowledge base documents",
  "Usage and cost history",
  "Sample orders (refunds and cancellations are undone)",
];

function summary(result: DemoReset): string {
  const d = result.deleted;
  const parts = [
    `${d.conversations ?? 0} conversations`,
    `${d.messages ?? 0} messages`,
    `${d.tickets ?? 0} tickets`,
    `${d.action_requests ?? 0} actions`,
    `${d.audit_events ?? 0} audit events`,
  ];
  const orders = result.mock_orders_reset;
  return `Deleted ${parts.join(", ")}. ${orders} order${orders === 1 ? "" : "s"} reset.`;
}

/**
 * Dev/demo only. Renders nothing unless the server has DEMO_TOOLS_ENABLED on and the
 * current user owns the workspace; the endpoint enforces both as well.
 */
export function ResetDemoData() {
  const { role, workspace } = useAuth();
  const demo = useDemoTools();
  const reset = useResetDemoData();
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const fieldId = useId();

  if (role !== "owner" || demo.data !== true || !workspace) return null;
  const matches = typed.trim() === workspace.name;

  async function confirm() {
    try {
      const result = await reset.mutateAsync();
      setOpen(false);
      setTyped("");
      toast.success(summary(result));
    } catch (error) {
      toast.error(errorMessage(error));
    }
  }

  return (
    <>
      <Button type="button" variant="destructive" onClick={() => setOpen(true)} className="gap-1.5">
        <Trash2 className="size-4" aria-hidden />
        Reset conversations &amp; inbox
      </Button>

      <AlertDialog
        open={open}
        onOpenChange={(next) => {
          if (reset.isPending) return;
          setOpen(next);
          if (!next) setTyped("");
        }}
      >
        <AlertDialogContent>
          <AlertDialogTitle>Reset conversations &amp; inbox?</AlertDialogTitle>
          <AlertDialogDescription>
            This permanently deletes this workspace&apos;s demo activity. It can&apos;t be undone.
          </AlertDialogDescription>
          <form
            className="flex flex-col gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              if (matches && !reset.isPending) void confirm();
            }}
          >
            <div className="grid gap-4 text-sm sm:grid-cols-2">
              <div className="flex flex-col gap-1.5">
                <h3 className="text-xs font-semibold text-urgent">Deleted</h3>
                <ul className="flex list-disc flex-col gap-1 pl-4 text-bone/90">
                  {DELETED.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
              <div className="flex flex-col gap-1.5">
                <h3 className="text-xs font-semibold text-resolved">Kept</h3>
                <ul className="flex list-disc flex-col gap-1 pl-4 text-bone/90">
                  {KEPT.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
            </div>
            <div className="flex flex-col gap-1.5">
              <label htmlFor={fieldId} className="text-xs text-ash">
                Type <span className="font-semibold text-bone">{workspace.name}</span> to confirm
              </label>
              <Input
                id={fieldId}
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                autoComplete="off"
                autoFocus
                disabled={reset.isPending}
              />
            </div>
            <AlertDialogFooter>
              <AlertDialogCancel disabled={reset.isPending}>Cancel</AlertDialogCancel>
              <Button type="submit" variant="destructive" disabled={!matches || reset.isPending}>
                {reset.isPending ? "Resetting…" : "Reset"}
              </Button>
            </AlertDialogFooter>
          </form>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
