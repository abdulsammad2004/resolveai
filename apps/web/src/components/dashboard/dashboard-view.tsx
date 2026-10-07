"use client";

import { SetupProgress } from "@/components/dashboard/setup-progress";
import { EmptyIllustration } from "@/components/empty-illustration";
import { PageHeader } from "@/components/page-header";
import { StatusChip, roleLabel, roleTone } from "@/components/status-chip";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useDocuments } from "@/lib/api/queries";
import { useAuth } from "@/lib/auth/auth-provider";

function greeting(date = new Date()): string {
  const hour = date.getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

export function DashboardView() {
  const { user, workspace, role } = useAuth();
  const documents = useDocuments();

  if (!user || !workspace || !role) return null;
  const firstName = user.full_name.trim().split(/\s+/)[0];

  // Tickets and approvals have no API yet, so their real count is 0.
  const stats = [
    {
      label: "Open tickets",
      value: 0 as number | null,
      loading: false,
      hint: "Messages from your chat widget will be counted here once ticket intake is live.",
    },
    {
      label: "Awaiting review",
      value: 0 as number | null,
      loading: false,
      hint: "Drafts and actions waiting for a person to approve them will be counted here.",
    },
    {
      label: "Documents",
      value: documents.data?.length ?? (documents.isError ? null : 0),
      loading: documents.isPending,
      hint: "Every help article and policy you upload, including ones still processing.",
    },
  ];

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

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {stats.map((stat) => (
          <Card key={stat.label} className="flex flex-col justify-between">
            <CardHeader className="pb-2">
              <span className="text-sm text-ash font-medium">{stat.label}</span>
              {stat.loading ? (
                <Skeleton className="mt-2 h-12 w-16" />
              ) : (
                <p className="font-display text-5xl sm:text-6xl font-black tracking-tight text-bone pt-1">
                  {stat.value ?? "–"}
                </p>
              )}
            </CardHeader>
            <CardContent>
              <p className="text-xs text-ash leading-relaxed">
                {stat.value === null ? "Couldn't load documents. Refresh to try again." : stat.hint}
              </p>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2 flex flex-col">
          <CardHeader className="pb-3 border-b border-line">
            <CardTitle className="text-lg">Activity</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-1 flex-col items-center justify-center gap-4 py-10 text-center">
            <EmptyIllustration kind="activity" className="size-20" />
            <p className="max-w-sm text-sm text-ash">
              Activity from your team and the assistant will show up here.
            </p>
          </CardContent>
        </Card>

        <SetupProgress />
      </div>
    </div>
  );
}
