import { cn } from "@/lib/utils";

// Placeholder block for loading data. The shimmer is dropped under reduced motion (globals.css).
export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden
      className={cn("skeleton relative overflow-hidden rounded-[6px] bg-white/[0.06]", className)}
      {...props}
    />
  );
}
