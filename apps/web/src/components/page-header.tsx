import type { ReactNode } from "react";

export function PageHeader({
  title,
  description,
  children,
}: {
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-2 px-1 pt-2 pb-1 sm:px-2 sm:pt-4">
      <h1 className="font-display text-4xl font-bold tracking-tight text-bone sm:text-5xl">
        {title}
      </h1>
      {description && <div className="max-w-2xl text-base text-ash">{description}</div>}
      {children}
    </div>
  );
}
