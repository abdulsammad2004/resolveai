"use client";

import { X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useSyncExternalStore } from "react";

import { Button } from "@/components/ui/button";

const SEQUENCE_TIMEOUT_MS = 1200;

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return (
    target.isContentEditable ||
    target.closest("input, textarea, select, [contenteditable='true'], [role='combobox']") !== null
  );
}

function subscribeNoop() {
  return () => {};
}

/** "⌘" on Apple platforms, "Ctrl" elsewhere. */
export function useModKeyLabel(): string {
  return useSyncExternalStore(
    subscribeNoop,
    () => (/Mac|iPhone|iPad/.test(navigator.platform) ? "⌘" : "Ctrl"),
    () => "Ctrl",
  );
}

/**
 * App-wide shortcuts: mod+K palette, "?" this sheet, "g d" dashboard, "g s" settings.
 * Single-key shortcuts are ignored while typing in a field.
 */
export function useAppShortcuts({
  togglePalette,
  toggleSheet,
}: {
  togglePalette: () => void;
  toggleSheet: () => void;
}) {
  const router = useRouter();
  const pendingG = useRef<number | null>(null);

  useEffect(() => {
    const clearPending = () => {
      if (pendingG.current !== null) window.clearTimeout(pendingG.current);
      pendingG.current = null;
    };

    const onKey = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        togglePalette();
        return;
      }
      if (e.metaKey || e.ctrlKey || e.altKey || e.defaultPrevented || isTypingTarget(e.target)) return;

      if (e.key === "?") {
        e.preventDefault();
        clearPending();
        toggleSheet();
        return;
      }
      if (pendingG.current !== null) {
        const dest = e.key === "d" ? "/dashboard" : e.key === "s" ? "/settings" : null;
        clearPending();
        if (dest) {
          e.preventDefault();
          router.push(dest);
        }
        return;
      }
      if (e.key === "g") {
        pendingG.current = window.setTimeout(clearPending, SEQUENCE_TIMEOUT_MS);
      }
    };

    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      clearPending();
    };
  }, [router, togglePalette, toggleSheet]);
}

function Keys({ keys }: { keys: string[] }) {
  return (
    <span className="flex items-center gap-1">
      {keys.map((k, i) => (
        <span key={i} className="flex items-center gap-1">
          {i > 0 && <span className="text-xs text-ash">then</span>}
          <kbd className="inline-flex h-6 min-w-6 items-center justify-center rounded-[4px] border border-line bg-carbon px-1.5 text-xs font-medium text-bone">
            {k}
          </kbd>
        </span>
      ))}
    </span>
  );
}

export function ShortcutsSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const mod = useModKeyLabel();
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previous?.focus();
    };
  }, [open, onClose]);

  if (!open) return null;

  const rows: { label: string; keys: string[] }[] = [
    { label: "Open the command palette", keys: [`${mod} K`] },
    { label: "Go to dashboard", keys: ["G", "D"] },
    { label: "Go to settings", keys: ["G", "S"] },
    { label: "Show keyboard shortcuts", keys: ["?"] },
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center sm:p-4">
      <div className="fixed inset-0 bg-ink/80 backdrop-blur-sm" aria-hidden onClick={onClose} />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="shortcuts-title"
        className="relative w-full max-w-md rounded-t-panel border border-line bg-carbon-elevated p-5 shadow-2xl animate-in fade-in-0 slide-in-from-bottom-4 duration-200 sm:rounded-panel"
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 id="shortcuts-title" className="text-base font-semibold text-bone">
            Keyboard shortcuts
          </h2>
          <Button ref={closeRef} variant="ghost" size="icon" aria-label="Close" onClick={onClose} className="size-8">
            <X className="size-4" aria-hidden />
          </Button>
        </div>
        <ul className="flex flex-col divide-y divide-line">
          {rows.map((row) => (
            <li key={row.label} className="flex items-center justify-between gap-4 py-3 text-sm text-bone">
              <span>{row.label}</span>
              <Keys keys={row.keys} />
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
