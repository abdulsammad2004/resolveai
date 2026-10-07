"use client";

import { Check, Circle } from "lucide-react";
import Link from "next/link";
import { useEffect } from "react";
import { motion, useAnimate, useReducedMotion } from "motion/react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { errorMessage } from "@/lib/api/errors";
import {
  useDocuments,
  useMembers,
  useUpdateWorkspaceSettings,
  useWorkspaceSettings,
} from "@/lib/api/queries";
import { useAuth } from "@/lib/auth/auth-provider";

/** Key inside workspace.settings (jsonb) recording that the widget was installed. */
const WIDGET_INSTALLED_KEY = "widget_installed";

const RING_RADIUS = 34;
const RING_LENGTH = 2 * Math.PI * RING_RADIUS;

export function SetupProgress() {
  const { workspace, role } = useAuth();
  const documents = useDocuments();
  const members = useMembers();
  const settings = useWorkspaceSettings();
  const update = useUpdateWorkspaceSettings();
  const canEdit = role === "owner" || role === "admin";

  const loading = documents.isPending || members.isPending || settings.isPending;

  const steps = [
    {
      key: "document",
      label: "Upload a document",
      hint: "Done once a document finishes processing.",
      done: documents.data?.some((d) => d.status === "ready") ?? false,
    },
    {
      key: "widget",
      label: "Install the chat widget",
      hint: "Copy your public key from settings into your site.",
      done: settings.data?.settings[WIDGET_INSTALLED_KEY] === true,
    },
    {
      key: "teammate",
      label: "Invite a teammate",
      hint: "Done once someone else joins this workspace.",
      done: (members.data?.length ?? 0) > 1,
    },
  ];
  const doneCount = steps.filter((s) => s.done).length;

  async function markWidgetDone() {
    if (!settings.data) return;
    try {
      // PATCH replaces the whole settings object, so merge with what is stored.
      await update.mutateAsync({
        settings: { ...settings.data.settings, [WIDGET_INSTALLED_KEY]: true },
      });
    } catch (err) {
      toast.error(errorMessage(err));
    }
  }

  return (
    <Card className="flex flex-col">
      <CardHeader className="border-b border-line pb-3">
        <CardTitle className="text-lg">Workspace setup</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        {loading ? (
          <div className="flex flex-col gap-4" aria-busy="true" aria-label="Loading setup progress">
            <Skeleton className="mx-auto size-24 rounded-full" />
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : (
          <>
            <ProgressRing done={doneCount} total={steps.length} workspaceId={workspace?.id} />
            <ul className="flex flex-col gap-2.5">
              {steps.map((step) => (
                <li
                  key={step.key}
                  className="flex items-start gap-3 rounded-[6px] border border-line bg-carbon-elevated p-3"
                >
                  {step.done ? (
                    <span className="mt-0.5 grid size-5 shrink-0 place-items-center rounded-full bg-resolved/15 text-resolved">
                      <Check className="size-3.5" aria-hidden />
                    </span>
                  ) : (
                    <Circle className="mt-0.5 size-5 shrink-0 text-ash" aria-hidden />
                  )}
                  <div className="min-w-0 flex-1">
                    <p className={`text-sm font-medium ${step.done ? "text-ash" : "text-bone"}`}>
                      {step.label}
                      <span className="sr-only">{step.done ? " (done)" : " (not done)"}</span>
                    </p>
                    {!step.done && <p className="mt-0.5 text-xs text-ash">{step.hint}</p>}
                    {!step.done && step.key === "document" && (
                      <Link href="/knowledge" className="mt-1.5 inline-block text-xs font-medium text-ion hover:underline">
                        Go to knowledge
                      </Link>
                    )}
                    {!step.done && step.key === "widget" && (
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        <Button asChild size="sm" variant="secondary">
                          <Link href="/settings">Open settings</Link>
                        </Button>
                        {canEdit ? (
                          <Button size="sm" variant="ghost" onClick={markWidgetDone} disabled={update.isPending}>
                            {update.isPending ? "Saving…" : "Mark as done"}
                          </Button>
                        ) : (
                          <span className="text-xs text-ash">An owner or admin can mark this done.</span>
                        )}
                      </div>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </>
        )}
      </CardContent>
    </Card>
  );
}

const SPARKS = Array.from({ length: 10 }, (_, i) => (i / 10) * Math.PI * 2);

/** Bursts sparks from the ring once per workspace per browser, the first time setup is seen complete. */
function useCelebration(complete: boolean, workspaceId: string | undefined) {
  const [scope, animate] = useAnimate<HTMLDivElement>();
  const still = useReducedMotion() ?? false;

  useEffect(() => {
    if (!complete || !workspaceId || still || !scope.current) return;
    const key = `resolveai:setup-celebrated:${workspaceId}`;
    try {
      if (localStorage.getItem(key)) return;
      localStorage.setItem(key, "1");
    } catch {
      return;
    }
    const sparks = Array.from(scope.current.children) as HTMLElement[];
    const controls = sparks.map((el, i) =>
      animate(
        el,
        {
          x: [0, Math.cos(SPARKS[i]) * 62],
          y: [0, Math.sin(SPARKS[i]) * 62],
          opacity: [1, 0],
          scale: [1, 0.4],
        },
        { duration: 1.1, ease: "easeOut", delay: 0.4 },
      ),
    );
    return () => controls.forEach((c) => c.stop());
  }, [complete, workspaceId, still, scope, animate]);

  return scope;
}

function ProgressRing({ done, total, workspaceId }: { done: number; total: number; workspaceId?: string }) {
  const still = useReducedMotion() ?? false;
  const complete = done === total;
  const offset = RING_LENGTH * (1 - done / total);
  const sparksRef = useCelebration(complete, workspaceId);

  return (
    <div className="flex items-center gap-4">
      <div className="relative size-24 shrink-0">
        <svg viewBox="0 0 80 80" className="size-full -rotate-90" aria-hidden>
          <circle cx="40" cy="40" r={RING_RADIUS} fill="none" strokeWidth="6" className="stroke-white/[0.08]" />
          <motion.circle
            cx="40"
            cy="40"
            r={RING_RADIUS}
            fill="none"
            strokeWidth="6"
            strokeLinecap="round"
            strokeDasharray={RING_LENGTH}
            className={complete ? "stroke-resolved" : "stroke-ion"}
            initial={still ? false : { strokeDashoffset: RING_LENGTH }}
            animate={{ strokeDashoffset: offset }}
            transition={{ duration: still ? 0 : 1, ease: [0.16, 1, 0.3, 1] }}
          />
        </svg>
        <div className="absolute inset-0 grid place-items-center">
          <span className="text-lg font-semibold text-bone">
            {done}/{total}
          </span>
        </div>
        <div ref={sparksRef} className="pointer-events-none absolute inset-0" aria-hidden>
          {SPARKS.map((_, i) => (
            <span
              key={i}
              style={{ opacity: 0 }}
              className={`absolute top-1/2 left-1/2 -mt-[3px] -ml-[3px] size-1.5 rounded-full ${i % 2 ? "bg-resolved" : "bg-ion"}`}
            />
          ))}
        </div>
      </div>
      <div aria-live="polite">
        <p className="text-sm font-semibold text-bone">
          {complete ? "You're all set" : `${done} of ${total} steps done`}
        </p>
        <p className="text-xs text-ash">
          {complete ? "Your workspace is ready for its first customers." : "Finish these to start answering customers."}
        </p>
      </div>
    </div>
  );
}
