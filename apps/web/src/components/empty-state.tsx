import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { GlassPanel } from "@/components/glass-panel";

export function EmptyState({
  icon: Icon,
  title,
  children,
  action,
}: {
  icon: LucideIcon;
  title: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <GlassPanel className="flex flex-col items-start gap-5 sm:p-10">
      <span className="grid size-12 place-items-center rounded-card bg-seafoam/12 text-seafoam">
        <Icon className="size-6" aria-hidden />
      </span>
      <div className="flex max-w-xl flex-col gap-2">
        <h2 className="text-xl font-semibold">{title}</h2>
        <p className="text-mist-dim">{children}</p>
      </div>
      {action}
    </GlassPanel>
  );
}
