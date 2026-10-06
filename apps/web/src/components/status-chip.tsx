import * as React from "react";
import { cn } from "cn";

export type ChipTone = "seafoam" | "amber" | "coral" | "neutral";

// Accent at 16% over a deep base, so the accent text keeps AA contrast on any glass.
const tones: Record<ChipTone, string> = {
  seafoam: "text-seafoam [--chip:rgb(127_224_200_/_0.16)]",
  amber: "text-amber [--chip:rgb(245_184_90_/_0.16)]",
  coral: "text-coral [--chip:rgb(255_138_122_/_0.16)]",
  neutral: "text-mist [--chip:rgb(255_255_255_/_0.1)]",
};

export function StatusChip({
  tone = "neutral",
  className,
  ...props
}: React.ComponentProps<"span"> & { tone?: ChipTone }) {
  return (
    <span
      className={cn(
        "inline-flex h-7 items-center gap-1.5 rounded-full bg-deep/60 bg-[linear-gradient(var(--chip),var(--chip))] px-3 text-sm font-medium whitespace-nowrap",
        tones[tone],
        className,
      )}
      {...props}
    />
  );
}

export const roleLabel: Record<"owner" | "admin" | "agent", string> = {
  owner: "Owner",
  admin: "Admin",
  agent: "Agent",
};

export const roleTone: Record<"owner" | "admin" | "agent", ChipTone> = {
  owner: "seafoam",
  admin: "neutral",
  agent: "neutral",
};
