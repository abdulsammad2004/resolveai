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
    <GlassPanel className="flex flex-col items-start gap-6 p-6 sm:p-10 border border-line bg-carbon rounded-panel">
      <span className="grid size-12 place-items-center rounded-[6px] bg-ion/15 text-ion border border-ion/20">
        <Icon className="size-6" aria-hidden />
      </span>
      <div className="flex max-w-2xl flex-col gap-2">
        <h2 className="font-display text-3xl font-bold uppercase tracking-tight text-bone sm:text-4xl">
          {title}
        </h2>
        <div className="text-base text-ash leading-relaxed">{children}</div>
      </div>
      {action && <div className="pt-2">{action}</div>}
    </GlassPanel>
  );
}
