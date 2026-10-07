"use client";

import { Menu, PanelLeftClose, PanelLeftOpen, Search, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import Link from "next/link";

import { Logo } from "@/components/logo";
import { Button } from "@/components/ui/button";
import { SidebarNav } from "./sidebar-nav";
import { UserMenu } from "./user-menu";
import { WorkspaceSwitcher } from "./workspace-switcher";
import { CommandPalette } from "./command-palette";

export function AppShell({ children }: { children: ReactNode }) {
  const [navOpen, setNavOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement>(null);

  const closeNav = useCallback(() => {
    setNavOpen(false);
    menuButtonRef.current?.focus();
  }, []);

  return (
    <div
      className={`min-h-dvh transition-[padding] duration-200 ${
        sidebarCollapsed ? "lg:pl-[72px]" : "lg:pl-[240px]"
      }`}
    >
      <a
        href="#main"
        className="fixed top-3 left-3 z-[60] -translate-y-24 rounded-[6px] bg-ion px-4 py-2 font-medium text-bone shadow-lg transition-transform focus:translate-y-0"
      >
        Skip to content
      </a>

      {/* Desktop sidebar */}
      <aside
        className={`fixed top-0 bottom-0 left-0 hidden flex-col border-r border-line bg-ink p-3 transition-[width] duration-200 lg:flex ${
          sidebarCollapsed ? "w-[72px]" : "w-[240px]"
        }`}
      >
        <div className="flex h-12 items-center justify-between px-2 pb-2">
          {!sidebarCollapsed ? (
            <Link href="/dashboard" className="transition-opacity hover:opacity-90">
              <Logo />
            </Link>
          ) : (
            <div className="mx-auto flex size-8 items-center justify-center rounded-[6px] bg-ion font-display text-lg font-black text-bone">
              R
            </div>
          )}
        </div>

        <div className="mt-4 flex-1">
          <SidebarNav collapsed={sidebarCollapsed} />
        </div>

        <div className="border-t border-line pt-3">
          <button
            type="button"
            onClick={() => setSidebarCollapsed((prev) => !prev)}
            title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            className="flex h-9 w-full items-center justify-center rounded-[6px] text-ash hover:bg-white/[0.04] hover:text-bone transition-colors"
          >
            {sidebarCollapsed ? (
              <PanelLeftOpen className="size-4" />
            ) : (
              <div className="flex w-full items-center gap-2 px-2 text-xs font-medium text-ash">
                <PanelLeftClose className="size-4" />
                <span>Collapse</span>
              </div>
            )}
          </button>
        </div>
      </aside>

      {/* Main Content & Topbar */}
      <div className="flex min-h-dvh flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-line bg-ink/90 px-4 backdrop-blur-md sm:px-6">
          <div className="flex items-center gap-3">
            <Button
              ref={menuButtonRef}
              variant="ghost"
              size="icon"
              className="lg:hidden text-bone"
              aria-label="Open navigation"
              aria-expanded={navOpen}
              aria-controls="mobile-nav"
              onClick={() => setNavOpen(true)}
            >
              <Menu className="size-5" aria-hidden />
            </Button>
            <WorkspaceSwitcher />
          </div>

          <div className="flex items-center gap-3">
            {/* Quick command palette trigger */}
            <button
              type="button"
              onClick={() => setCommandPaletteOpen(true)}
              className="flex h-9 items-center gap-2 rounded-[6px] border border-line bg-carbon px-3 text-xs text-ash hover:border-white/20 hover:text-bone transition-colors"
            >
              <Search className="size-3.5" />
              <span className="hidden sm:inline">Search...</span>
              <kbd className="hidden font-mono text-[10px] text-ash sm:inline bg-carbon-elevated px-1.5 py-0.5 rounded border border-line">
                ⌘K
              </kbd>
            </button>

            <UserMenu />
          </div>
        </header>

        <main id="main" tabIndex={-1} className="flex-1 bg-ink p-4 outline-none sm:p-6 lg:p-8">
          {children}
        </main>
      </div>

      {/* Command Palette Modal */}
      <CommandPalette open={commandPaletteOpen} onOpenChange={setCommandPaletteOpen} />

      {/* Mobile drawer */}
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
        className="fixed inset-0 bg-ink/80 backdrop-blur-sm duration-150 animate-in fade-in-0"
        aria-hidden
        onClick={onClose}
      />
      <div
        ref={panelRef}
        id="mobile-nav"
        role="dialog"
        aria-modal="true"
        aria-label="Navigation"
        className="fixed top-0 bottom-0 left-0 flex w-[260px] flex-col border-r border-line bg-ink p-4 shadow-2xl animate-in slide-in-from-left duration-200"
      >
        <div className="flex items-center justify-between pb-4 border-b border-line">
          <Logo />
          <Button variant="ghost" size="icon" aria-label="Close navigation" onClick={onClose}>
            <X className="size-5 text-bone" aria-hidden />
          </Button>
        </div>
        <div className="mt-4 flex-1">
          <SidebarNav onNavigate={onClose} />
        </div>
      </div>
    </div>
  );
}
