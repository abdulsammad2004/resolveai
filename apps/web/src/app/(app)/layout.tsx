"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { FullPageLoader } from "@/components/full-page-loader";
import { AppShell } from "@/components/shell/app-shell";
import { useAuth } from "@/lib/auth/auth-provider";
import { wasSignedOutByUser } from "@/lib/auth/session-store";

// Client-side guard: signed-out visitors go to /login?next=<path>.
export default function AppLayout({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    if (status !== "unauthenticated") return;
    router.replace(
      wasSignedOutByUser() ? "/login" : `/login?next=${encodeURIComponent(pathname)}`,
    );
  }, [status, pathname, router]);

  if (status !== "authenticated") {
    return <FullPageLoader label={status === "loading" ? undefined : "Taking you to log in"} />;
  }

  return <AppShell>{children}</AppShell>;
}
