"use client";

import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import Link from "next/link";

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
    <div className="min-h-screen bg-ink text-bone flex flex-col justify-center selection:bg-ion selection:text-bone">
      <main className="mx-auto grid min-h-dvh w-full max-w-[1240px] grid-cols-1 items-center gap-8 px-4 py-8 sm:px-6 lg:grid-cols-[minmax(0,460px)_minmax(0,1fr)] lg:gap-16 lg:px-10">
        <div className="flex w-full flex-col gap-8 rounded-panel border border-line bg-carbon p-6 sm:p-10 shadow-2xl">
          <Link href="/" className="inline-block transition-opacity hover:opacity-90">
            <Logo />
          </Link>
          {children}
        </div>
        <div className="hidden justify-center lg:flex">
          <ProductPreview />
        </div>
      </main>
    </div>
  );
}
