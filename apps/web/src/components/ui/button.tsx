import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "cn"
import { Slot } from "radix-ui"

const buttonVariants = cva(
  "pressable inline-flex shrink-0 items-center justify-center gap-2 rounded-card font-medium whitespace-nowrap select-none disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        primary:
          "bg-seafoam text-deep transition-[filter,transform] hover:brightness-110",
        secondary: "glass glass-interactive text-mist",
        destructive: "glass glass-interactive text-coral",
        ghost:
          "text-mist-dim transition-colors hover:bg-white/[0.07] hover:text-mist",
        link: "text-seafoam underline-offset-4 hover:underline",
      },
      size: {
        default: "h-11 px-5 text-base",
        sm: "h-9 px-3.5 text-sm",
        lg: "h-12 px-6 text-base",
        icon: "size-10",
      },
    },
    defaultVariants: {
      variant: "primary",
      size: "default",
    },
  }
)

function Button({
  className,
  variant = "primary",
  size = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean
  }) {
  const Comp = asChild ? Slot.Root : "button"

  return (
    <Comp
      data-slot="button"
      data-variant={variant}
      data-size={size}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }
