"use client";

import { Toaster as Sonner, type ToasterProps } from "sonner";
import { CircleCheckIcon, InfoIcon, TriangleAlertIcon, OctagonXIcon, Loader2Icon } from "lucide-react";

const Toaster = ({ ...props }: ToasterProps) => {
  return (
    <Sonner
      theme="dark"
      position="bottom-right"
      icons={{
        success: <CircleCheckIcon className="size-4 text-resolved" />,
        info: <InfoIcon className="size-4 text-ion" />,
        warning: <TriangleAlertIcon className="size-4 text-review" />,
        error: <OctagonXIcon className="size-4 text-urgent" />,
        loading: <Loader2Icon className="size-4 animate-spin text-ash" />,
      }}
      toastOptions={{
        unstyled: true,
        classNames: {
          toast:
            "flex w-full items-center gap-3 rounded-[8px] border border-line-strong bg-carbon-elevated px-4 py-3.5 text-sm text-bone shadow-2xl duration-200",
          description: "text-xs text-ash mt-0.5",
        },
      }}
      {...props}
    />
  );
};

export { Toaster };
