import * as React from "react";
import { cn } from "cn";

// Page-level glass panel: 24px radius, generous padding.
export function GlassPanel({
  className,
  as: Comp = "section",
  ...props
}: React.HTMLAttributes<HTMLElement> & { as?: "section" | "div" }) {
  return <Comp className={cn("glass rounded-panel p-6 sm:p-8", className)} {...props} />;
}
