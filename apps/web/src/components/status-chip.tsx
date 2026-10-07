import * as React from "react";
import { cn } from "@/lib/utils";

export type ChipTone = "resolved" | "review" | "urgent" | "neutral" | "ion";

const tones: Record<ChipTone, string> = {
  resolved: "text-resolved bg-resolved/10 border-resolved/20",
  review: "text-review bg-review/10 border-review/20",
  urgent: "text-urgent bg-urgent/10 border-urgent/20",
  ion: "text-ion bg-ion/10 border-ion/20",
  neutral: "text-ash bg-white/[0.04] border-line",
};

export function StatusChip({
  tone = "neutral",
  dot = false,
  className,
  children,
  ...props
}: React.ComponentProps<"span"> & { tone?: ChipTone; dot?: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex h-6 items-center gap-1.5 rounded-[4px] border px-2 text-xs font-medium tracking-wide whitespace-nowrap select-none",
        tones[tone],
        className
      )}
      {...props}
    >
      {dot && (
        <span
          className={cn(
            "size-1.5 rounded-full",
            tone === "resolved" && "bg-resolved pulse-active",
            tone === "review" && "bg-review",
            tone === "urgent" && "bg-urgent",
            tone === "ion" && "bg-ion",
            tone === "neutral" && "bg-ash"
          )}
          aria-hidden
        />
      )}
      {children}
    </span>
  );
}

export const roleLabel: Record<"owner" | "admin" | "agent", string> = {
  owner: "Owner",
  admin: "Admin",
  agent: "Agent",
};

export const roleTone: Record<"owner" | "admin" | "agent", ChipTone> = {
  owner: "ion",
  admin: "neutral",
  agent: "neutral",
};
