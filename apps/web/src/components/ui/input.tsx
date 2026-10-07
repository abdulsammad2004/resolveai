import * as React from "react";
import { cn } from "@/lib/utils";

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        "h-10 w-full min-w-0 rounded-[6px] border border-line bg-carbon-input px-3.5 text-sm text-bone transition-colors placeholder:text-ash/60 hover:border-line-strong focus-visible:border-ion focus-visible:ring-1 focus-visible:ring-ion focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50 read-only:cursor-default read-only:hover:border-line aria-invalid:border-urgent aria-invalid:ring-urgent",
        className
      )}
      {...props}
    />
  );
}

export { Input };
