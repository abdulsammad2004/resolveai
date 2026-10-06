import { BookOpenText, Sparkles } from "lucide-react";

import { StatusChip } from "@/components/status-chip";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";

/*
 * Static product preview for the auth screens, built from real components.
 * `inert` keeps it out of the tab order and stops clicks; it is illustration only.
 */
export function ProductPreview() {
  return (
    <figure className="flex w-full max-w-[560px] flex-col gap-4">
      <div
        inert
        aria-label="Example: ResolveAI drafts a reply to a customer and waits for your approval"
        role="img"
        className="glass flex flex-col gap-5 rounded-panel p-6 sm:p-8"
      >
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <Avatar>
              <AvatarFallback>MR</AvatarFallback>
            </Avatar>
            <div className="leading-tight">
              <p className="font-medium text-mist">Maya Robinson</p>
              <p className="text-sm text-mist-dim">Chat · 2 min ago</p>
            </div>
          </div>
          <StatusChip tone="neutral">Order status</StatusChip>
        </div>

        <div className="max-w-[85%] rounded-card rounded-tl-md border border-white/10 bg-white/[0.06] px-4 py-3 text-mist">
          Hi, my order #4821 hasn&apos;t arrived yet. Can you check?
        </div>

        <div className="glass-elevated ml-auto flex w-[92%] flex-col gap-4 rounded-card p-5">
          <div className="flex flex-wrap items-center gap-2">
            <span className="mr-auto inline-flex items-center gap-2 text-sm font-medium text-seafoam">
              <Sparkles className="size-4" aria-hidden />
              AI draft
            </span>
            <StatusChip tone="neutral">
              <BookOpenText className="size-3.5" aria-hidden />
              Shipping policy
            </StatusChip>
            <StatusChip tone="amber">Awaiting review</StatusChip>
          </div>
          <p className="text-mist">
            Your order shipped on Monday and is due Thursday. Here&apos;s the tracking
            link…
          </p>
          <div className="flex flex-wrap gap-3">
            <Button size="sm">Approve and send</Button>
            <Button size="sm" variant="secondary">
              Edit
            </Button>
          </div>
        </div>
      </div>
      <figcaption className="px-2 text-base text-mist-dim">
        AI drafts the reply. Your team approves it.
      </figcaption>
    </figure>
  );
}
