import { cn } from "cn";

export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <svg viewBox="0 0 28 28" className="size-7" aria-hidden>
        <rect width="28" height="28" rx="9" fill="rgb(127 224 200 / 0.16)" />
        <path
          d="M7 16.5c2.2-2.4 4.4-2.4 6.6 0s4.4 2.4 6.6 0M7 11.5c2.2-2.4 4.4-2.4 6.6 0s4.4 2.4 6.6 0"
          fill="none"
          stroke="#7FE0C8"
          strokeWidth="2"
          strokeLinecap="round"
        />
      </svg>
      <span className="font-heading text-lg font-semibold tracking-[-0.02em] text-mist">
        ResolveAI
      </span>
    </span>
  );
}
