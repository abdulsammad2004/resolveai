import { BookOpenText, Check, Sparkles } from "lucide-react";
import { StatusChip } from "@/components/status-chip";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";

export function ProductPreview() {
  return (
    <figure className="flex w-full max-w-[560px] flex-col gap-4">
      <div
        inert
        aria-label="Example: ResolveAI drafts a reply to a customer and waits for your approval"
        role="img"
        className="flex flex-col gap-5 rounded-panel border border-line bg-carbon p-6 sm:p-8 shadow-2xl"
      >
        <div className="flex items-center justify-between gap-4 border-b border-line pb-4">
          <div className="flex items-center gap-3">
            <Avatar className="border border-line bg-carbon-elevated text-xs font-semibold text-bone">
              <AvatarFallback>MR</AvatarFallback>
            </Avatar>
            <div className="leading-tight">
              <p className="font-semibold text-bone">Maya Robinson</p>
              <p className="text-xs text-ash">Live chat · 2 min ago</p>
            </div>
          </div>
          <StatusChip tone="neutral">Ticket #1042</StatusChip>
        </div>

        {/* Customer bubble */}
        <div className="max-w-[85%] rounded-[6px] border border-line bg-carbon-elevated px-4 py-3 text-sm text-bone">
          Hi, my order #4821 hasn&apos;t arrived yet. Can you check?
        </div>

        {/* AI Agent draft card */}
        <div className="ml-auto flex w-[94%] flex-col gap-4 rounded-[6px] border border-ion/30 bg-ion/[0.04] p-5 shadow-lg">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="inline-flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-ion">
              <Sparkles className="size-3.5" aria-hidden />
              AI Grounded Draft
            </span>
            <div className="flex items-center gap-2">
              <StatusChip tone="neutral">
                <BookOpenText className="size-3 mr-1" aria-hidden />
                Shipping policy §4
              </StatusChip>
              <StatusChip tone="review">Awaiting review</StatusChip>
            </div>
          </div>

          <p className="text-sm text-bone leading-relaxed">
            Your package is in transit via Express Air and scheduled for delivery by Thursday, 4:00 PM. Here is your tracking status.
          </p>

          <div className="flex items-center gap-2 pt-1 border-t border-line">
            <Button size="sm" className="gap-1.5">
              <Check className="size-3.5" />
              Approve and send
            </Button>
            <Button size="sm" variant="secondary">
              Edit draft
            </Button>
          </div>
        </div>
      </div>
      <figcaption className="flex items-center justify-between px-2 text-xs font-mono text-ash uppercase tracking-wider">
        <span>Grounded retrieval</span>
        <span>Zero hallucinations</span>
      </figcaption>
    </figure>
  );
}
