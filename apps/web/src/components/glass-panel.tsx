import * as React from "react";
import { cn } from "@/lib/utils";

// Solid carbon panel: 16px radius, border-line, rich contrast.
export function GlassPanel({
  className,
  as: Comp = "section",
  ...props
}: React.HTMLAttributes<HTMLElement> & { as?: "section" | "div" }) {
  return (
    <Comp
      className={cn(
        "rounded-panel border border-line bg-carbon p-6 sm:p-8 text-bone transition-colors",
        className
      )}
      {...props}
    />
  );
}
