import { cn } from "@/lib/utils";

export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5 select-none", className)}>
      <span className="flex size-7 items-center justify-center rounded-[6px] bg-ion text-ink shadow-[0_0_16px_rgba(123,108,255,0.4)]">
        <svg viewBox="0 0 16 16" className="size-4" fill="none" aria-hidden>
          <path
            d="M3 4.5L8 2L13 4.5V11.5L8 14L3 11.5V4.5Z"
            stroke="currentColor"
            strokeWidth="1.75"
            strokeLinejoin="round"
          />
          <path
            d="M8 6.5V9.5M6.5 8H9.5"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
          />
        </svg>
      </span>
      <span className="font-display text-xl font-bold tracking-tight text-bone">
        ResolveAI
      </span>
    </span>
  );
}
