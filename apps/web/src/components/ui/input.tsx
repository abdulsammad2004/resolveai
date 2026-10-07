import * as React from "react"
import { cn } from "cn"

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        "glass-input h-11 w-full min-w-0 rounded-card px-3.5 text-base text-mist transition-colors placeholder:text-mist-dim/70 hover:border-white/25 disabled:cursor-not-allowed disabled:opacity-60 read-only:cursor-default read-only:hover:border-border aria-invalid:border-coral/70",
        className
      )}
      {...props}
    />
  )
}

export { Input }
