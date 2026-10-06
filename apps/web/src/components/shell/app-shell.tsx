"use client";

import { Menu, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

import { Logo } from "@/components/logo";
import { Button } from "@/components/ui/button";
import { SidebarNav } from "./sidebar-nav";
import { UserMenu } from "./user-menu";
import { WorkspaceSwitcher } from "./workspace-switcher";

// Stagger index for the one orchestrated entrance (see DESIGN.md, "Motion").
const rise = (i: number) => ({ "--i": i }) as CSSProperties;

export function AppShell({ children }: { children: ReactNode }) {
  const [navOpen, setNavOpen] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement>(null);

  const closeNav = useCallback(() => {
    setNavOpen(false);
    menuButtonRef.current?.focus();
  }, []);

  return (
    <div className="min-h-dvh lg:pl-[284px]">
      <a
        href="#main"
        className="glass-elevated fixed top-3 left-3 z-[60] -translate-y-24 rounded-card px-4 py-2.5 font-medium text-mist focus:translate-y-0"
      >
        Skip to content
      </a>

      {/* Floating sidebar, inset 12px from the screen edges. */}
      <aside
        style={rise(0)}
        className="glass rise-in fixed top-3 bottom-3 left-3 hidden w-[260px] flex-col gap-8 overflow-y-auto rounded-panel p-5 lg:flex"
      >
        <div className="px-2 pt-1">
          <Logo />
        </div>
        <SidebarNav />
      </aside>

      <div className="flex min-h-dvh flex-col gap-3 p-3 lg:pl-0">
        <header
          style={rise(1)}
          className="glass rise-in relative z-30 flex items-center gap-3 rounded-panel px-3 py-2.5 sm:px-4"
        >
          <Button
            ref={menuButtonRef}
            variant="ghost"
            size="icon"
            className="lg:hidden"
            aria-label="Open navigation"
            aria-expanded={navOpen}
            aria-controls="mobile-nav"
            onClick={() => setNavOpen(true)}
          >
            <Menu className="size-5" aria-hidden />
          </Button>
          <WorkspaceSwitcher />
          <div className="ml-auto">
            <UserMenu />
          </div>
        </header>

        <main id="main" tabIndex={-1} style={rise(2)} className="rise-in flex-1 outline-none">
          {children}
        </main>
      </div>

      {navOpen && <MobileNav onClose={closeNav} />}
    </div>
  );
}

function MobileNav({ onClose }: { onClose: () => void }) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    panelRef.current?.querySelector<HTMLElement>("a, button")?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const { overflow } = document.body.style;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
    };
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 lg:hidden">
      <div
        className="absolute inset-0 bg-deep/60 duration-150 animate-in fade-in-0"
        aria-hidden
        onClick={onClose}
      />
      <div
        ref={panelRef}
        id="mobile-nav"
        role="dialog"
        aria-modal="true"
        aria-label="Navigation"
        className="glass-elevated slide-over absolute top-3 bottom-3 left-3 flex w-[min(280px,calc(100vw-24px))] flex-col gap-8 overflow-y-auto rounded-panel p-5"
      >
        <div className="flex items-center justify-between pl-2">
          <Logo />
          <Button variant="ghost" size="icon" aria-label="Close navigation" onClick={onClose}>
            <X className="size-5" aria-hidden />
          </Button>
        </div>
        <SidebarNav onNavigate={onClose} />
      </div>
    </div>
  );
}
