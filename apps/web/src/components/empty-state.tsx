import type { ReactNode } from "react";
import { EmptyIllustration, type IllustrationKind } from "@/components/empty-illustration";
import { GlassPanel } from "@/components/glass-panel";

export function EmptyState({
  illustration,
  title,
  children,
  action,
}: {
  illustration: IllustrationKind;
  title: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <GlassPanel className="flex flex-col items-start gap-6 p-6 sm:p-10 border border-line bg-carbon rounded-panel">
      <EmptyIllustration kind={illustration} className="size-20 sm:size-24" />
      <div className="flex max-w-2xl flex-col gap-2">
        <h2 className="font-display text-3xl font-bold tracking-tight text-bone sm:text-4xl">
          {title}
        </h2>
        <div className="text-base text-ash leading-relaxed">{children}</div>
      </div>
      {action && <div className="pt-2">{action}</div>}
    </GlassPanel>
  );
}
