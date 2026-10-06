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
    <div className="flex flex-col gap-3 px-2 pt-4 pb-2 sm:px-4 sm:pt-6">
      <h1 className="text-2xl font-semibold sm:text-3xl">{title}</h1>
      {description && <div className="max-w-2xl text-lg text-mist-dim">{description}</div>}
      {children}
    </div>
  );
}
