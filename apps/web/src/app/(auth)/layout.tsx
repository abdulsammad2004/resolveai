"use client";

import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { ProductPreview } from "@/components/auth/product-preview";
import { FullPageLoader } from "@/components/full-page-loader";
import { Logo } from "@/components/logo";
import { safeNextPath, useAuth } from "@/lib/auth/auth-provider";

export default function AuthLayout({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const router = useRouter();

  // Signed-in users (including right after login or signup) go to ?next= or the dashboard.
  useEffect(() => {
    if (status !== "authenticated") return;
    const next = new URLSearchParams(window.location.search).get("next");
    router.replace(safeNextPath(next));
  }, [status, router]);

  if (status !== "unauthenticated") {
    return <FullPageLoader label={status === "loading" ? undefined : "Opening your workspace"} />;
  }

  return (
    <main className="mx-auto grid min-h-dvh w-full max-w-[1240px] grid-cols-[minmax(0,1fr)] items-center gap-8 px-4 py-8 sm:px-6 lg:grid-cols-[minmax(0,460px)_minmax(0,1fr)] lg:gap-12 lg:px-10">
      <div className="glass flex w-full flex-col gap-8 rounded-panel p-6 sm:p-8">
        <Logo />
        {children}
      </div>
      <div className="hidden justify-center lg:flex">
        <ProductPreview />
      </div>
    </main>
  );
}
