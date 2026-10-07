"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Command } from "cmdk";
import {
  BookOpen,
  Inbox,
  LayoutDashboard,
  LogOut,
  MessagesSquare,
  Search,
  Settings,
  ShieldCheck,
  Building2,
} from "lucide-react";
import { useAuth } from "@/lib/auth/auth-provider";
import { useWorkspaces } from "@/lib/api/queries";
import { toast } from "sonner";
import { errorMessage } from "@/lib/api/errors";

interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function CommandPalette({ open, onOpenChange }: CommandPaletteProps) {
  const router = useRouter();
  const { workspace, switchWorkspace, logout } = useAuth();
  const workspaces = useWorkspaces();

  // Keyboard shortcut listener
  React.useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        onOpenChange(!open);
      }
    };

    document.addEventListener("keydown", down);
    return () => document.removeEventListener("keydown", down);
  }, [open, onOpenChange]);

  const runCommand = React.useCallback(
    (command: () => void) => {
      onOpenChange(false);
      command();
    },
    [onOpenChange]
  );

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Command Palette"
      className="fixed inset-0 z-50 flex items-start justify-center pt-[15vh] px-4"
    >
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-ink/80 backdrop-blur-sm transition-opacity"
        onClick={() => onOpenChange(false)}
        aria-hidden
      />

      {/* Dialog container */}
      <div className="relative w-full max-w-lg rounded-panel border border-line bg-carbon-elevated shadow-2xl overflow-hidden animate-in fade-in-0 zoom-in-95 duration-150">
        <Command
          className="flex flex-col w-full text-bone"
          loop
          label="Command Menu"
        >
          <div className="flex items-center border-b border-line px-3">
            <Search className="mr-2 size-4 shrink-0 text-ash" aria-hidden />
            <Command.Input
              autoFocus
              placeholder="Type a command or search..."
              className="flex h-12 w-full rounded-md bg-transparent py-3 text-sm text-bone outline-none placeholder:text-ash disabled:cursor-not-allowed disabled:opacity-50"
            />
            <kbd className="hidden sm:inline-flex h-5 select-none items-center gap-1 rounded border border-line bg-carbon px-1.5 font-mono text-[10px] font-medium text-ash">
              ESC
            </kbd>
          </div>

          <Command.List className="max-h-[320px] overflow-y-auto p-2 outline-none">
            <Command.Empty className="py-6 text-center text-sm text-ash">
              No results found.
            </Command.Empty>

            <Command.Group
              heading="Navigation"
              className="px-2 py-1.5 text-xs font-semibold text-ash uppercase tracking-wider [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:text-ash"
            >
              <Command.Item
                value="dashboard overview"
                onSelect={() => runCommand(() => router.push("/dashboard"))}
                className="relative flex cursor-pointer select-none items-center rounded-[6px] px-2.5 py-2 text-sm text-bone outline-none aria-selected:bg-ion aria-selected:text-bone data-[selected=true]:bg-ion data-[selected=true]:text-bone transition-colors"
              >
                <LayoutDashboard className="mr-2.5 size-4" />
                <span>Dashboard</span>
              </Command.Item>

              <Command.Item
                value="tickets inbox support"
                onSelect={() => runCommand(() => router.push("/tickets"))}
                className="relative flex cursor-pointer select-none items-center rounded-[6px] px-2.5 py-2 text-sm text-bone outline-none aria-selected:bg-ion aria-selected:text-bone data-[selected=true]:bg-ion data-[selected=true]:text-bone transition-colors"
              >
                <Inbox className="mr-2.5 size-4" />
                <span>Inbox / Tickets</span>
              </Command.Item>

              <Command.Item
                value="approvals reviews actions"
                onSelect={() => runCommand(() => router.push("/approvals"))}
                className="relative flex cursor-pointer select-none items-center rounded-[6px] px-2.5 py-2 text-sm text-bone outline-none aria-selected:bg-ion aria-selected:text-bone data-[selected=true]:bg-ion data-[selected=true]:text-bone transition-colors"
              >
                <ShieldCheck className="mr-2.5 size-4" />
                <span>Approvals</span>
              </Command.Item>

              <Command.Item
                value="conversations live chat"
                onSelect={() => runCommand(() => router.push("/conversations"))}
                className="relative flex cursor-pointer select-none items-center rounded-[6px] px-2.5 py-2 text-sm text-bone outline-none aria-selected:bg-ion aria-selected:text-bone data-[selected=true]:bg-ion data-[selected=true]:text-bone transition-colors"
              >
                <MessagesSquare className="mr-2.5 size-4" />
                <span>Conversations</span>
              </Command.Item>

              <Command.Item
                value="knowledge base articles documentation"
                onSelect={() => runCommand(() => router.push("/knowledge"))}
                className="relative flex cursor-pointer select-none items-center rounded-[6px] px-2.5 py-2 text-sm text-bone outline-none aria-selected:bg-ion aria-selected:text-bone data-[selected=true]:bg-ion data-[selected=true]:text-bone transition-colors"
              >
                <BookOpen className="mr-2.5 size-4" />
                <span>Knowledge</span>
              </Command.Item>

              <Command.Item
                value="settings workspace api keys"
                onSelect={() => runCommand(() => router.push("/settings"))}
                className="relative flex cursor-pointer select-none items-center rounded-[6px] px-2.5 py-2 text-sm text-bone outline-none aria-selected:bg-ion aria-selected:text-bone data-[selected=true]:bg-ion data-[selected=true]:text-bone transition-colors"
              >
                <Settings className="mr-2.5 size-4" />
                <span>Settings</span>
              </Command.Item>
            </Command.Group>

            {workspaces.data && workspaces.data.length > 0 && (
              <Command.Group
                heading="Workspaces"
                className="px-2 py-1.5 text-xs font-semibold text-ash uppercase tracking-wider mt-2 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:text-ash"
              >
                {workspaces.data.map((ws) => (
                  <Command.Item
                    key={ws.id}
                    value={`workspace ${ws.name}`}
                    onSelect={() =>
                      runCommand(async () => {
                        if (ws.id === workspace?.id) return;
                        try {
                          await switchWorkspace(ws.id);
                          toast.success(`Switched to ${ws.name}`);
                        } catch (err) {
                          toast.error(errorMessage(err));
                        }
                      })
                    }
                    className="relative flex cursor-pointer select-none items-center justify-between rounded-[6px] px-2.5 py-2 text-sm text-bone outline-none aria-selected:bg-ion aria-selected:text-bone data-[selected=true]:bg-ion data-[selected=true]:text-bone transition-colors"
                  >
                    <div className="flex items-center">
                      <Building2 className="mr-2.5 size-4" />
                      <span>{ws.name}</span>
                    </div>
                    {ws.id === workspace?.id && (
                      <span className="text-xs font-mono opacity-80">(Active)</span>
                    )}
                  </Command.Item>
                ))}
              </Command.Group>
            )}

            <Command.Group
              heading="Actions"
              className="px-2 py-1.5 text-xs font-semibold text-ash uppercase tracking-wider mt-2 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:text-ash"
            >
              <Command.Item
                value="logout signout"
                onSelect={() => runCommand(() => void logout())}
                className="relative flex cursor-pointer select-none items-center rounded-[6px] px-2.5 py-2 text-sm text-urgent outline-none aria-selected:bg-urgent/20 data-[selected=true]:bg-urgent/20 transition-colors"
              >
                <LogOut className="mr-2.5 size-4" />
                <span>Log out</span>
              </Command.Item>
            </Command.Group>
          </Command.List>
        </Command>
      </div>
    </div>
  );
}

