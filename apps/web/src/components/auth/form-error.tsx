import { CircleAlert } from "lucide-react";
import type { ReactNode } from "react";

// Inline error under a form, announced to screen readers.
export function FormError({ children }: { children: ReactNode }) {
  if (!children) return null;
  return (
    <div
      role="alert"
      className="flex items-start gap-2.5 rounded-[6px] border border-urgent/30 bg-urgent/10 px-4 py-3 text-sm text-bone"
    >
      <CircleAlert className="mt-0.5 size-4 shrink-0 text-urgent" aria-hidden />
      <p>{children}</p>
    </div>
  );
}
