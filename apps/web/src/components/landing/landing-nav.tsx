"use client";

import Link from "next/link";
import { Logo } from "@/components/logo";
import { StatusChip } from "@/components/status-chip";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth/auth-provider";

export function LandingNav() {
  const { status } = useAuth();
  const isAuthenticated = status === "authenticated";

  return (
    <header className="sticky top-0 z-40 w-full border-b border-line bg-ink/90 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
        <Link href="/" className="transition-opacity hover:opacity-90">
          <Logo />
        </Link>

        {/* System status pill */}
        <div className="hidden md:flex items-center gap-2">
          <StatusChip tone="resolved" dot={true}>
            All systems operational
          </StatusChip>
        </div>

        {/* Auth CTA Actions */}
        <div className="flex items-center gap-3">
          {isAuthenticated ? (
            <Button asChild size="sm">
              <Link href="/dashboard">Open dashboard</Link>
            </Button>
          ) : (
            <>
              <Button asChild variant="ghost" size="sm">
                <Link href="/login">Log in</Link>
              </Button>
              <Button asChild size="sm">
                <Link href="/signup">Start free</Link>
              </Button>
            </>
          )}
        </div>
      </div>
    </header>
  );
}

