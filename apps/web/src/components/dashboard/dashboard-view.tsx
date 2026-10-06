"use client";

import { BookOpen } from "lucide-react";
import Link from "next/link";

import { EmptyState } from "@/components/empty-state";
import { GlassPanel } from "@/components/glass-panel";
import { PageHeader } from "@/components/page-header";
import { StatusChip, roleLabel, roleTone } from "@/components/status-chip";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth/auth-provider";

function greeting(date = new Date()): string {
  const hour = date.getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

const STATS = [
  {
    label: "Open tickets",
    hint: "Customer conversations that still need a reply will be counted here.",
    accent: "text-mist",
  },
  {
    label: "Awaiting review",
    hint: "AI drafts and actions waiting for someone on your team to approve them.",
    accent: "text-amber",
  },
  {
    label: "Documents",
    hint: "Help articles and policies the assistant can cite when it drafts a reply.",
    accent: "text-mist",
  },
] as const;

export function DashboardView() {
  const { user, workspace, role } = useAuth();
  if (!user || !workspace || !role) return null;
  const firstName = user.full_name.trim().split(/\s+/)[0];

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title={`${greeting()}, ${firstName}`}
        description={
          <p className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <span>
              You&apos;re working in <span className="font-medium text-mist">{workspace.name}</span>
            </span>
            <StatusChip tone={roleTone[role]}>{roleLabel[role]}</StatusChip>
          </p>
        }
      />

      <div className="grid gap-4 md:grid-cols-3">
        {STATS.map((stat) => (
          <GlassPanel key={stat.label} className="flex flex-col gap-3">
            <h2 className="flex items-center gap-2 font-sans text-base font-medium tracking-normal text-mist-dim">
              {stat.label === "Awaiting review" && (
                <span className="size-2 rounded-full bg-amber" aria-hidden />
              )}
              {stat.label}
            </h2>
            <p className={`font-heading text-3xl font-semibold ${stat.accent}`}>
              <span aria-hidden>—</span>
              <span className="sr-only">No data yet</span>
            </p>
            <p className="text-sm text-mist-dim">{stat.hint}</p>
          </GlassPanel>
        ))}
      </div>

      <EmptyState
        icon={BookOpen}
        title="Add your first documents so the assistant can answer questions"
        action={
          <Button asChild>
            <Link href="/knowledge">Add documents</Link>
          </Button>
        }
      >
        The assistant only answers from your own help articles and policies, and hands anything it
        can&apos;t ground to a person on your team.
      </EmptyState>
    </div>
  );
}
