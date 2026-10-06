import * as React from "react"
import { cn } from "cn"

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        "glass-input field-sizing-content min-h-24 w-full min-w-0 rounded-card px-3.5 py-2.5 text-base text-mist transition-colors placeholder:text-mist-dim/70 hover:border-white/25 disabled:cursor-not-allowed disabled:opacity-60 read-only:cursor-default read-only:hover:border-border aria-invalid:border-coral/70",
        className
      )}
      {...props}
    />
  )
}

export { Textarea }
