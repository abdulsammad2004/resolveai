import * as React from "react";
import { cn } from "@/lib/utils";

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        "flex min-h-[80px] w-full rounded-[6px] border border-line bg-carbon-input px-3.5 py-2.5 text-sm text-bone transition-colors placeholder:text-ash/60 hover:border-line-strong focus-visible:border-ion focus-visible:ring-1 focus-visible:ring-ion focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50 read-only:cursor-default read-only:hover:border-line aria-invalid:border-urgent aria-invalid:ring-urgent",
        className
      )}
      {...props}
    />
  );
}

export { Textarea };
