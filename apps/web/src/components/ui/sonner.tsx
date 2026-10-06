"use client"

import { Toaster as Sonner, type ToasterProps } from "sonner"
import { CircleCheckIcon, InfoIcon, TriangleAlertIcon, OctagonXIcon, Loader2Icon } from "lucide-react"

// Dark only; toasts are elevated glass with accent-coloured icons.
const Toaster = ({ ...props }: ToasterProps) => {
  return (
    <Sonner
      theme="dark"
      position="bottom-right"
      icons={{
        success: <CircleCheckIcon className="size-4 text-seafoam" />,
        info: <InfoIcon className="size-4 text-mist-dim" />,
        warning: <TriangleAlertIcon className="size-4 text-amber" />,
        error: <OctagonXIcon className="size-4 text-coral" />,
        loading: <Loader2Icon className="size-4 animate-spin text-mist-dim" />,
      }}
      toastOptions={{
        unstyled: true,
        classNames: {
          toast:
            "glass-elevated flex w-full items-center gap-3 rounded-card px-4 py-3 text-base text-mist",
          description: "text-sm text-mist-dim",
        },
      }}
      {...props}
    />
  )
}

export { Toaster }
