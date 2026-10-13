"use client";

import { ThumbsDown, ThumbsUp } from "lucide-react";
import { useState, type ReactNode } from "react";

import { SetupProgress } from "@/components/dashboard/setup-progress";
import { PageHeader } from "@/components/page-header";
import { StatusChip, roleLabel, roleTone } from "@/components/status-chip";
import { intentLabels, priorityLabel } from "@/components/tickets/ticket-chips";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { errorMessage } from "@/lib/api/errors";
import {
  useAnalyticsOverview,
  useKnowledgeGaps,
  type AnalyticsOverview,
  type AnalyticsRange,
  type KnowledgeGaps,
  type TicketIntent,
  type TicketPriority,
} from "@/lib/api/queries";
import { useAuth } from "@/lib/auth/auth-provider";
import { cn } from "@/lib/utils";
import {
  formatCount,
  formatDuration,
  formatPercent,
  formatRelative,
  formatUsd,
  formatUsdAxis,
} from "./analytics-format";
import {
  ChartEmpty,
  HorizontalBars,
  SERIES,
  STATUS,
  StackedDayBars,
  StackedRows,
  TimeLineChart,
  type SeriesSpec,
} from "./charts";

const RANGES: { days: AnalyticsRange; label: string }[] = [
  { days: 7, label: "7 days" },
  { days: 30, label: "30 days" },
  { days: 90, label: "90 days" },
];

const CONVERSATION_SERIES: SeriesSpec[] = [
  { key: "conversations", label: "Conversations", color: SERIES[0] },
  { key: "contained", label: "AI-contained", color: SERIES[1] },
  { key: "handed_off", label: "Handed off", color: SERIES[2] },
];

// Same order as the API's cost groups; colors follow the purpose, whatever is in range.
const COST_SERIES: SeriesSpec[] = [
  { key: "classify", label: "Classify", color: SERIES[0] },
  { key: "answer", label: "Answer", color: SERIES[1] },
  { key: "agent", label: "Agent", color: SERIES[2] },
  { key: "draft", label: "Draft", color: SERIES[3] },
  { key: "embedding", label: "Embeddings", color: SERIES[4] },
];
const PURPOSE_LABEL: Record<string, string> = Object.fromEntries(
  COST_SERIES.map((s) => [s.key, s.label]),
);

// Action outcomes are states, so they wear the status colors (with labels in the legend).
const ACTION_SERIES: SeriesSpec[] = [
  { key: "succeeded", label: "Succeeded", color: STATUS.good },
  { key: "in_progress", label: "Approved, running", color: SERIES[0] },
  { key: "proposed", label: "Waiting for approval", color: STATUS.warning },
  { key: "rejected", label: "Rejected", color: STATUS.neutral },
  { key: "failed", label: "Failed", color: STATUS.critical },
];

const TOOL_LABEL: Record<string, string> = {
  issue_refund: "Refund",
  cancel_order: "Cancel order",
};

function greeting(date = new Date()): string {
  const hour = date.getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

function humanize(key: string): string {
  const text = key.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function DashboardView() {
  const { user, workspace, role } = useAuth();
  const [days, setDays] = useState<AnalyticsRange>(30);
  const overview = useAnalyticsOverview(days);
  const gaps = useKnowledgeGaps(days);

  if (!user || !workspace || !role) return null;
  const firstName = user.full_name.trim().split(/\s+/)[0];
  const data = overview.data;

  return (
    <div className="flex flex-col gap-6 max-w-7xl mx-auto">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
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
        <RangePicker value={days} onChange={setDays} busy={overview.isFetching} />
      </div>

      {overview.isError && !data ? (
        <Card>
          <p className="text-sm text-urgent">
            Couldn&apos;t load analytics. {errorMessage(overview.error)}
          </p>
        </Card>
      ) : (
        <>
          <KpiTiles data={data} />

          <div className="grid gap-6 lg:grid-cols-3">
            <ChartCard
              className="lg:col-span-2"
              title="Conversations"
              subtitle="Widget conversations started each day (UTC)."
            >
              {!data ? (
                <Skeleton className="h-64 w-full" />
              ) : data.conversations.total === 0 ? (
                <ChartEmpty>No widget conversations in this range yet.</ChartEmpty>
              ) : (
                <TimeLineChart
                  data={data.series}
                  series={CONVERSATION_SERIES}
                  formatValue={formatCount}
                  label={`Conversations per day over the last ${days} days`}
                />
              )}
            </ChartCard>
            <TicketBreakdown data={data} />
          </div>

          <div className="grid gap-6 lg:grid-cols-3">
            <ChartCard
              className="lg:col-span-2"
              title="AI cost"
              subtitle="Model spend per day, by what it was used for."
            >
              {!data ? (
                <Skeleton className="h-64 w-full" />
              ) : data.llm.calls === 0 ? (
                <ChartEmpty>No model calls in this range.</ChartEmpty>
              ) : (
                <StackedDayBars
                  data={data.llm.daily}
                  series={COST_SERIES}
                  formatValue={formatUsd}
                  formatAxis={formatUsdAxis}
                  axisWidth={64}
                  label={`Model cost per day over the last ${days} days`}
                />
              )}
            </ChartCard>
            <CostBreakdown data={data} />
          </div>

          <div className="grid gap-6 lg:grid-cols-3">
            <DraftReview data={data} />
            <ActionApprovals data={data} />
            <Satisfaction data={data} />
          </div>

          <div className="grid gap-6 lg:grid-cols-3">
            <KnowledgeGapsCard className="lg:col-span-2" gaps={gaps.data} error={gaps.isError} />
            <SetupProgress />
          </div>
        </>
      )}
    </div>
  );
}

function RangePicker({
  value,
  onChange,
  busy,
}: {
  value: AnalyticsRange;
  onChange: (days: AnalyticsRange) => void;
  busy: boolean;
}) {
  return (
    <div
      role="radiogroup"
      aria-label="Date range"
      aria-busy={busy}
      className="inline-flex self-start rounded-control border border-line bg-carbon p-1 lg:self-auto"
    >
      {RANGES.map((range) => {
        const selected = range.days === value;
        return (
          <button
            key={range.days}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => onChange(range.days)}
            className={cn(
              "pressable rounded-[4px] px-3 py-1.5 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ion",
              selected ? "bg-ion text-ink" : "text-ash hover:text-bone",
            )}
          >
            {range.label}
          </button>
        );
      })}
    </div>
  );
}

function ChartCard({
  title,
  subtitle,
  className,
  children,
}: {
  title: string;
  subtitle?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Card className={cn("flex flex-col", className)}>
      <CardHeader className="gap-1">
        <CardTitle className="text-lg">{title}</CardTitle>
        {subtitle && <p className="text-xs text-ash">{subtitle}</p>}
      </CardHeader>
      <CardContent className="flex-1">{children}</CardContent>
    </Card>
  );
}

type Tile = { label: string; value: string; detail: ReactNode };

function KpiTiles({ data }: { data: AnalyticsOverview | undefined }) {
  if (!data) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 8 }, (_, i) => (
          <Card key={i} className="gap-3">
            <Skeleton className="h-4 w-28" />
            <Skeleton className="h-10 w-20" />
            <Skeleton className="h-3 w-36" />
          </Card>
        ))}
      </div>
    );
  }
  const c = data.conversations;
  const t = data.tickets;
  const d = data.drafts;
  const s = data.satisfaction;
  const ups = s.answer_up + s.resolution_up;
  const ratings = ups + s.answer_down + s.resolution_down;
  const sent = d.sent_as_is + d.sent_edited;

  const tiles: Tile[] = [
    {
      label: "Conversations",
      value: formatCount(c.total),
      detail: c.total ? `${formatCount(c.handed_off)} handed off to the team` : "None in this range yet",
    },
    {
      label: "AI-contained rate",
      value: formatPercent(c.contained_rate),
      detail: c.total ? conversationOutcomes(c) : "None in this range yet",
    },
    {
      label: "Handoff rate",
      value: formatPercent(c.handoff_rate),
      detail: "Conversations that became a ticket",
    },
    {
      label: "First response",
      value: formatDuration(t.first_response.median_s),
      detail: t.first_response.count
        ? `Median · p90 ${formatDuration(t.first_response.p90_s)} · ${formatCount(t.first_response.count)} tickets`
        : "No replies sent yet",
    },
    {
      label: "Time to resolution",
      value: formatDuration(t.resolution.median_s),
      detail: t.resolution.count
        ? `Median · p90 ${formatDuration(t.resolution.p90_s)} · ${formatCount(t.resolution.count)} resolved`
        : "No tickets resolved yet",
    },
    {
      label: "Draft edit rate",
      value: formatPercent(d.edit_rate),
      detail: sent
        ? `${formatCount(sent)} AI drafts sent · ${formatPercent(d.acceptance_rate)} accepted`
        : "No AI drafts sent yet",
    },
    {
      label: "Customer satisfaction",
      value: formatPercent(ratings ? ups / ratings : null),
      detail: ratings ? `${formatCount(ups)} of ${formatCount(ratings)} ratings positive` : "No ratings yet",
    },
    {
      label: "AI cost",
      value: formatUsd(data.llm.total_cost_usd),
      detail: data.llm.cost_per_conversation !== null
        ? `${formatUsd(data.llm.cost_per_conversation)} per conversation`
        : `${formatCount(data.llm.calls)} model calls`,
    },
  ];

  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {tiles.map((tile) => (
        <Card key={tile.label} className="gap-2">
          <span className="text-sm font-medium text-ash">{tile.label}</span>
          <p className="font-display text-5xl font-black tracking-tight text-bone tabular-nums">
            {tile.value}
          </p>
          <p className="text-xs leading-relaxed text-ash">{tile.detail}</p>
        </Card>
      ))}
    </div>
  );
}

function TicketBreakdown({ data }: { data: AnalyticsOverview | undefined }) {
  return (
    <ChartCard title="Tickets" subtitle="Requests handed to the team, by intent and priority.">
      {!data ? (
        <Skeleton className="h-64 w-full" />
      ) : data.tickets.total === 0 ? (
        <ChartEmpty>No tickets in this range.</ChartEmpty>
      ) : (
        <div className="flex flex-col gap-5">
          <div>
            <h4 className="mb-1 text-xs font-medium text-ash">By intent</h4>
            <HorizontalBars
              items={data.tickets.by_intent.map((i) => ({
                key: i.key,
                label: intentLabels[i.key as TicketIntent] ?? humanize(i.key),
                value: i.count,
              }))}
              formatValue={formatCount}
              valueName="Tickets"
              label="Tickets by intent"
            />
          </div>
          <div>
            <h4 className="mb-1 text-xs font-medium text-ash">By priority</h4>
            <HorizontalBars
              items={data.tickets.by_priority.map((i) => ({
                key: i.key,
                label: priorityLabel[i.key as TicketPriority] ?? humanize(i.key),
                value: i.count,
              }))}
              formatValue={formatCount}
              valueName="Tickets"
              label="Tickets by priority"
            />
          </div>
        </div>
      )}
    </ChartCard>
  );
}

/** Disjoint parts that add up to the total: the optional ones only show when non-zero. */
function conversationOutcomes(c: AnalyticsOverview["conversations"]): string {
  const noReply = c.total - c.contained - c.fallback_ended - c.thumbs_down_ended - c.handed_off;
  return [
    `${formatCount(c.contained)} contained`,
    `${formatCount(c.fallback_ended)} fell back, no ticket`,
    `${formatCount(c.handed_off)} handed off`,
    c.thumbs_down_ended > 0 && `${formatCount(c.thumbs_down_ended)} thumbs down, no ticket`,
    noReply > 0 && `${formatCount(noReply)} no reply yet`,
  ]
    .filter(Boolean)
    .join(" · ");
}

function CostBreakdown({ data }: { data: AnalyticsOverview | undefined }) {
  return (
    <ChartCard title="Cost by model" subtitle="Calls, errors and spend in this range.">
      {!data ? (
        <Skeleton className="h-64 w-full" />
      ) : data.llm.calls === 0 ? (
        <ChartEmpty>Costs appear once the assistant answers or drafts.</ChartEmpty>
      ) : (
        <div className="flex flex-col gap-5">
          <table className="w-full text-sm">
            <caption className="sr-only">Model usage by model</caption>
            <thead>
              <tr className="text-left text-xs text-ash">
                <th className="pb-2 font-medium">Model</th>
                <th className="pb-2 text-right font-medium">Calls</th>
                <th className="pb-2 text-right font-medium">Errors</th>
                <th className="pb-2 text-right font-medium">Cost</th>
              </tr>
            </thead>
            <tbody>
              {data.llm.by_model.map((m) => (
                <tr key={m.model} className="border-t border-line">
                  <td className="max-w-36 truncate py-2 text-bone" title={m.model}>{m.model}</td>
                  <td className="py-2 text-right tabular-nums text-bone">{formatCount(m.calls)}</td>
                  <td className={cn("py-2 text-right tabular-nums", m.errors ? "text-urgent" : "text-ash")}>
                    {formatCount(m.errors)}
                  </td>
                  <td className="py-2 text-right tabular-nums text-bone">{formatUsd(m.cost_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div>
            <h4 className="mb-2 text-xs font-medium text-ash">By purpose</h4>
            <ul className="flex flex-col gap-1.5 text-sm">
              {data.llm.by_purpose.map((p) => {
                const color = COST_SERIES.find((s) => s.key === p.purpose)?.color ?? STATUS.neutral;
                return (
                  <li key={p.purpose} className="flex items-center gap-2">
                    <span className="size-2 rounded-full" style={{ background: color }} aria-hidden />
                    <span className="text-ash">{PURPOSE_LABEL[p.purpose] ?? humanize(p.purpose)}</span>
                    <span className="ml-auto tabular-nums text-bone">{formatUsd(p.cost_usd)}</span>
                  </li>
                );
              })}
            </ul>
          </div>
        </div>
      )}
    </ChartCard>
  );
}

function DraftReview({ data }: { data: AnalyticsOverview | undefined }) {
  const d = data?.drafts;
  const total = d ? d.sent_as_is + d.sent_edited + d.rejected : 0;
  return (
    <ChartCard title="AI drafts" subtitle="How reviewers handled reply drafts the AI wrote.">
      {!d ? (
        <Skeleton className="h-40 w-full" />
      ) : total === 0 ? (
        <ChartEmpty>No AI drafts were reviewed in this range.</ChartEmpty>
      ) : (
        <HorizontalBars
          items={[
            { key: "as_is", label: "Sent as written", value: d.sent_as_is },
            { key: "edited", label: "Edited, then sent", value: d.sent_edited },
            { key: "rejected", label: "Rejected", value: d.rejected },
          ]}
          formatValue={formatCount}
          valueName="Drafts"
          label="AI draft outcomes"
        />
      )}
    </ChartCard>
  );
}

function ActionApprovals({ data }: { data: AnalyticsOverview | undefined }) {
  return (
    <ChartCard title="Action approvals" subtitle="Refunds and other actions the AI proposed.">
      {!data ? (
        <Skeleton className="h-40 w-full" />
      ) : data.actions.length === 0 ? (
        <ChartEmpty>No actions were proposed in this range.</ChartEmpty>
      ) : (
        <StackedRows
          data={data.actions.map((a) => ({
            label: TOOL_LABEL[a.tool_name] ?? humanize(a.tool_name),
            succeeded: a.succeeded,
            in_progress: Math.max(0, a.approved - a.succeeded - a.failed),
            proposed: a.proposed,
            rejected: a.rejected,
            failed: a.failed,
          }))}
          series={ACTION_SERIES}
          label="Action outcomes by action type"
        />
      )}
    </ChartCard>
  );
}

function RatingSplit({ label, up, down }: { label: string; up: number; down: number }) {
  const total = up + down;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between text-sm">
        <span className="text-ash">{label}</span>
        <span className="tabular-nums text-bone">{total ? formatPercent(up / total) : "–"}</span>
      </div>
      {total === 0 ? (
        <p className="text-xs text-ash">No ratings yet.</p>
      ) : (
        <>
          <div
            className="flex h-2.5 gap-0.5 overflow-hidden rounded-full"
            role="img"
            aria-label={`${label}: ${up} positive, ${down} negative`}
          >
            {up > 0 && <span className="bg-resolved" style={{ width: `${(up / total) * 100}%` }} />}
            {down > 0 && <span className="bg-urgent" style={{ width: `${(down / total) * 100}%` }} />}
          </div>
          <div className="flex justify-between text-xs text-ash">
            <span className="flex items-center gap-1">
              <ThumbsUp className="size-3.5 text-resolved" aria-hidden /> {formatCount(up)} helpful
            </span>
            <span className="flex items-center gap-1">
              <ThumbsDown className="size-3.5 text-urgent" aria-hidden /> {formatCount(down)} not helpful
            </span>
          </div>
        </>
      )}
    </div>
  );
}

function Satisfaction({ data }: { data: AnalyticsOverview | undefined }) {
  const s = data?.satisfaction;
  return (
    <ChartCard title="Customer satisfaction" subtitle="Ratings from the chat widget.">
      {!s ? (
        <Skeleton className="h-40 w-full" />
      ) : (
        <div className="flex flex-col gap-6">
          <RatingSplit label="Assistant answers" up={s.answer_up} down={s.answer_down} />
          <RatingSplit label="Resolved conversations" up={s.resolution_up} down={s.resolution_down} />
        </div>
      )}
    </ChartCard>
  );
}

function KnowledgeGapsCard({
  gaps,
  error,
  className,
}: {
  gaps: KnowledgeGaps | undefined;
  error: boolean;
  className?: string;
}) {
  const max = Math.max(1, ...(gaps?.gaps.map((g) => g.count) ?? [1]));
  return (
    <ChartCard
      className={className}
      title="Knowledge gaps"
      subtitle="Questions the assistant couldn't answer from your help docs, grouped by similarity."
    >
      {error && !gaps ? (
        <p className="text-sm text-urgent">Couldn&apos;t load knowledge gaps. Refresh to try again.</p>
      ) : !gaps ? (
        <Skeleton className="h-48 w-full" />
      ) : gaps.gaps.length === 0 ? (
        <ChartEmpty>
          Every question in this range was answered from your docs. Gaps show up here when the
          assistant has to say it couldn&apos;t find something.
        </ChartEmpty>
      ) : (
        <div className="flex flex-col gap-3">
          <p className="text-xs text-ash">
            {formatCount(gaps.total_fallbacks)} unanswered{" "}
            {gaps.total_fallbacks === 1 ? "question" : "questions"} in this range. Add or update
            articles that cover the top ones.
          </p>
          <ol className="flex flex-col">
            {gaps.gaps.map((gap, i) => (
              <li
                key={`${gap.question}-${i}`}
                className="grid grid-cols-[1fr_auto] items-center gap-x-4 gap-y-1.5 border-t border-line py-3 first:border-t-0"
              >
                <p className="text-sm text-bone">{gap.question}</p>
                <span className="text-right text-sm font-semibold tabular-nums text-bone">
                  {formatCount(gap.count)}
                  <span className="sr-only"> times</span>
                </span>
                <div className="h-1 overflow-hidden rounded-full bg-line" aria-hidden>
                  <div className="h-full rounded-full bg-ion" style={{ width: `${(gap.count / max) * 100}%` }} />
                </div>
                <span className="text-right text-xs text-ash">{formatRelative(gap.last_seen)}</span>
              </li>
            ))}
          </ol>
        </div>
      )}
    </ChartCard>
  );
}
