"use client";

import { useEffect, useState } from "react";
import {
  CheckCircle2,
  Circle,
  Sparkles,
  Terminal,
} from "lucide-react";
import Link from "next/link";
import { useMotionValue, useTransform, animate } from "motion/react";

import { PageHeader } from "@/components/page-header";
import { StatusChip, roleLabel, roleTone } from "@/components/status-chip";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "@/lib/auth/auth-provider";

function greeting(date = new Date()): string {
  const hour = date.getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

function AnimatedNumber({ value, suffix = "", decimals = 0 }: { value: number; suffix?: string; decimals?: number }) {
  const count = useMotionValue(0);
  useTransform(count, (latest) =>
    decimals > 0 ? latest.toFixed(decimals) : Math.round(latest).toString()
  );
  const [displayValue, setDisplayValue] = useState("0");

  useEffect(() => {
    const controls = animate(count, value, {
      duration: 1.4,
      ease: [0.16, 1, 0.3, 1],
      onUpdate: (latest) => {
        setDisplayValue(decimals > 0 ? latest.toFixed(decimals) : Math.round(latest).toString());
      },
    });
    return () => controls.stop();
  }, [value, count, decimals]);

  return (
    <span>
      {displayValue}
      {suffix}
    </span>
  );
}

const STATS = [
  {
    label: "Resolved today",
    value: 142,
    suffix: "",
    decimals: 0,
    hint: "AI handled end-to-end with human verification",
    tone: "text-bone",
  },
  {
    label: "Grounded accuracy",
    value: 98.4,
    suffix: "%",
    decimals: 1,
    hint: "Backed by verified documentation citations",
    tone: "text-resolved",
  },
  {
    label: "Avg resolution time",
    value: 18,
    suffix: "s",
    decimals: 0,
    hint: "From ticket intake to drafted & approved response",
    tone: "text-ion",
  },
];

const SYNTHETIC_LOGS = [
  { time: "Just now", text: "Retrieved policy chunk #419 (Refund Terms §3.2)" },
  { time: "1m ago", text: "Drafted refund approval for ticket #1084 ($49.00)" },
  { time: "3m ago", text: "Verified tenant isolation constraint (workspace_id match)" },
  { time: "6m ago", text: "Resolved query: 'How do I invite team members?'" },
  { time: "9m ago", text: "Logged approval state change by admin@company.com" },
];

export function DashboardView() {
  const { user, workspace, role } = useAuth();

  const [checklist, setChecklist] = useState({
    docs: false,
    team: false,
    ticket: false,
  });

  const toggleCheck = (key: keyof typeof checklist) => {
    setChecklist((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  if (!user || !workspace || !role) return null;
  const firstName = user.full_name.trim().split(/\s+/)[0];

  return (
    <div className="flex flex-col gap-6 max-w-7xl mx-auto">
      <PageHeader
        title={`${greeting()}, ${firstName}`}
        description={
          <p className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <span>
              You&apos;re working in <span className="font-semibold text-bone">{workspace.name}</span>
            </span>
            <StatusChip tone={roleTone[role]}>{roleLabel[role]}</StatusChip>
          </p>
        }
      />

      {/* Bento Grid: 3 Count-up Stats */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {STATS.map((stat) => (
          <Card key={stat.label} className="flex flex-col justify-between">
            <CardHeader className="pb-2">
              <span className="text-xs uppercase tracking-wider text-ash font-medium">
                {stat.label}
              </span>
              <CardTitle className={`font-display text-5xl sm:text-6xl font-black tracking-tight ${stat.tone} pt-1`}>
                <AnimatedNumber value={stat.value} suffix={stat.suffix} decimals={stat.decimals} />
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-ash leading-relaxed">{stat.hint}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Bento Grid: Split wide live activity stream + narrow onboarding checklist */}
      <div className="grid gap-6 lg:grid-cols-3">
        {/* Wide Tile: Live AI activity stream */}
        <Card className="lg:col-span-2 flex flex-col">
          <CardHeader className="flex flex-row items-center justify-between pb-3 border-b border-line">
            <div className="flex items-center gap-2.5">
              <Terminal className="size-4 text-ion" />
              <CardTitle className="text-lg font-bold text-bone font-display tracking-tight">
                Live AI Activity Stream
              </CardTitle>
            </div>
            <StatusChip tone="resolved" dot={true}>
              Realtime
            </StatusChip>
          </CardHeader>
          <CardContent className="pt-4 flex-1">
            <div className="space-y-3 font-mono text-xs">
              {SYNTHETIC_LOGS.map((log, index) => (
                <div
                  key={index}
                  className="flex items-start justify-between gap-4 rounded-[6px] bg-carbon-elevated p-2.5 border border-line/60"
                >
                  <div className="flex items-start gap-2.5">
                    <span className="mt-0.5 size-1.5 rounded-full bg-ion" />
                    <span className="text-bone">{log.text}</span>
                  </div>
                  <span className="shrink-0 text-ash text-[11px]">{log.time}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Narrow Tile: Get Started Checklist */}
        <Card className="flex flex-col justify-between">
          <div>
            <CardHeader className="pb-3 border-b border-line">
              <div className="flex items-center gap-2">
                <Sparkles className="size-4 text-ion" />
                <CardTitle className="text-lg font-bold text-bone font-display tracking-tight">
                  Getting Started
                </CardTitle>
              </div>
            </CardHeader>
            <CardContent className="pt-4 space-y-3">
              <button
                type="button"
                onClick={() => toggleCheck("docs")}
                className="w-full text-left flex items-start gap-3 p-3 rounded-[6px] border border-line bg-carbon-elevated hover:border-white/20 transition-colors"
              >
                {checklist.docs ? (
                  <CheckCircle2 className="size-5 text-resolved shrink-0 mt-0.5" />
                ) : (
                  <Circle className="size-5 text-ash shrink-0 mt-0.5" />
                )}
                <div>
                  <p className={`text-sm font-medium ${checklist.docs ? "line-through text-ash" : "text-bone"}`}>
                    Connect knowledge base
                  </p>
                  <p className="text-xs text-ash mt-0.5">Upload verified documentation or FAQ articles.</p>
                </div>
              </button>

              <button
                type="button"
                onClick={() => toggleCheck("team")}
                className="w-full text-left flex items-start gap-3 p-3 rounded-[6px] border border-line bg-carbon-elevated hover:border-white/20 transition-colors"
              >
                {checklist.team ? (
                  <CheckCircle2 className="size-5 text-resolved shrink-0 mt-0.5" />
                ) : (
                  <Circle className="size-5 text-ash shrink-0 mt-0.5" />
                )}
                <div>
                  <p className={`text-sm font-medium ${checklist.team ? "line-through text-ash" : "text-bone"}`}>
                    Invite team agents
                  </p>
                  <p className="text-xs text-ash mt-0.5">Set permissions for humans to approve critical actions.</p>
                </div>
              </button>

              <button
                type="button"
                onClick={() => toggleCheck("ticket")}
                className="w-full text-left flex items-start gap-3 p-3 rounded-[6px] border border-line bg-carbon-elevated hover:border-white/20 transition-colors"
              >
                {checklist.ticket ? (
                  <CheckCircle2 className="size-5 text-resolved shrink-0 mt-0.5" />
                ) : (
                  <Circle className="size-5 text-ash shrink-0 mt-0.5" />
                )}
                <div>
                  <p className={`text-sm font-medium ${checklist.ticket ? "line-through text-ash" : "text-bone"}`}>
                    Simulate first test ticket
                  </p>
                  <p className="text-xs text-ash mt-0.5">Test grounded retrieval with strict tenant boundary.</p>
                </div>
              </button>
            </CardContent>
          </div>

          <CardContent className="pt-2">
            <Button asChild className="w-full" size="sm">
              <Link href="/knowledge">Explore knowledge base</Link>
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
