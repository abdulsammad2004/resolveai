"use client";

import type { ReactNode } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { EmptyIllustration } from "@/components/empty-illustration";
import { formatDay, formatLongDay } from "./analytics-format";

/*
 * Chart tokens, from DESIGN.md. Recharts paints SVG attributes, so these are hex values
 * mirroring the CSS variables in globals.css.
 *
 * SERIES is the categorical order (identity), assigned in order and never cycled. Slot 1 is
 * the brand ion; the rest are the reference dark-mode hues. Validated on the carbon surface
 * (#17191E): lightness band, chroma, contrast >= 3:1, worst adjacent CVD ΔE 8.4, worst
 * normal-vision ΔE 19.3. Status colors (resolved/review/urgent) are only used for states.
 */
export const SERIES = ["#7B6CFF", "#d95926", "#199e70", "#c98500", "#d55181"] as const;
export const STATUS = { good: "#4FD1A5", warning: "#FFB547", critical: "#FF5C5C", neutral: "#8B9099" };
const SURFACE = "#17191E";
const GRID = "rgba(255,255,255,0.06)";
const AXIS_TEXT = "#8B9099";
const AXIS = { fontSize: 12, fill: AXIS_TEXT };

export type SeriesSpec = { key: string; label: string; color: string };

type TooltipEntry = {
  name?: string | number;
  value?: number | string | ReadonlyArray<number | string>;
  color?: string;
  dataKey?: unknown;
};

type TooltipProps = {
  active?: boolean;
  payload?: ReadonlyArray<TooltipEntry>;
  label?: string | number;
};

/** Tooltip in the app's surface: the series swatch carries identity, text stays in ink. */
export function ChartTooltip({
  active,
  payload,
  label,
  formatValue,
  formatLabel = (l) => l,
  total,
}: TooltipProps & {
  formatValue: (value: number) => string;
  formatLabel?: (label: string) => string;
  total?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="min-w-40 rounded-control border border-line-strong bg-carbon-elevated px-3 py-2 text-xs shadow-none">
      {label !== undefined && (
        <p className="mb-1.5 font-medium text-bone">{formatLabel(String(label))}</p>
      )}
      <ul className="flex flex-col gap-1">
        {payload.map((entry) => (
          <li key={String(entry.dataKey ?? entry.name)} className="flex items-center gap-2">
            <span className="size-2 shrink-0 rounded-full" style={{ background: entry.color }} aria-hidden />
            <span className="text-ash">{entry.name}</span>
            <span className="ml-auto pl-3 font-medium tabular-nums text-bone">
              {formatValue(Number(entry.value ?? 0))}
            </span>
          </li>
        ))}
      </ul>
      {total && (
        <p className="mt-1.5 flex border-t border-line pt-1.5 text-ash">
          Total <span className="ml-auto font-medium tabular-nums text-bone">{total}</span>
        </p>
      )}
    </div>
  );
}

function LegendContent({ series }: { series: SeriesSpec[] }) {
  return (
    <ul className="flex flex-wrap justify-end gap-x-4 gap-y-1 pb-3 text-xs text-ash">
      {series.map((s) => (
        <li key={s.key} className="flex items-center gap-1.5">
          <span className="h-0.5 w-3 rounded-full" style={{ background: s.color }} aria-hidden />
          {s.label}
        </li>
      ))}
    </ul>
  );
}

export function ChartEmpty({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-full min-h-40 flex-col items-center justify-center gap-3 py-6 text-center">
      <EmptyIllustration kind="activity" className="size-14 opacity-80" />
      <p className="max-w-xs text-sm text-ash">{children}</p>
    </div>
  );
}

/** Change over time: thin lines, crosshair tooltip, legend for 2+ series. */
export function TimeLineChart<T extends { day: string }>({
  data,
  series,
  formatValue,
  height = 260,
  label,
}: {
  data: T[];
  series: SeriesSpec[];
  formatValue: (value: number) => string;
  height?: number;
  label: string;
}) {
  return (
    <div role="img" aria-label={label} style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -12 }}>
          <CartesianGrid vertical={false} stroke={GRID} />
          <XAxis
            dataKey="day"
            tickFormatter={formatDay}
            tick={AXIS}
            axisLine={false}
            tickLine={false}
            minTickGap={24}
          />
          <YAxis tick={AXIS} axisLine={false} tickLine={false} allowDecimals={false} width={44} />
          <Tooltip
            cursor={{ stroke: "rgba(255,255,255,0.18)", strokeWidth: 1 }}
            content={(props) => (
              <ChartTooltip {...(props as TooltipProps)} formatValue={formatValue} formatLabel={formatLongDay} />
            )}
          />
          {series.length > 1 && (
            <Legend verticalAlign="top" align="right" content={() => <LegendContent series={series} />} />
          )}
          {series.map((s) => (
            <Line
              key={s.key}
              type="monotone"
              dataKey={s.key}
              name={s.label}
              stroke={s.color}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, stroke: SURFACE, strokeWidth: 2 }}
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Stacked daily bars (e.g. cost by purpose). 1px surface strokes give the segment gap. */
export function StackedDayBars<T extends { day: string }>({
  data,
  series,
  formatValue,
  height = 260,
  label,
}: {
  data: T[];
  series: SeriesSpec[];
  formatValue: (value: number) => string;
  height?: number;
  label: string;
}) {
  return (
    <div role="img" aria-label={label} style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -4 }} barCategoryGap="20%">
          <CartesianGrid vertical={false} stroke={GRID} />
          <XAxis
            dataKey="day"
            tickFormatter={formatDay}
            tick={AXIS}
            axisLine={false}
            tickLine={false}
            minTickGap={24}
          />
          <YAxis tick={AXIS} axisLine={false} tickLine={false} tickFormatter={formatValue} width={56} />
          <Tooltip
            cursor={{ fill: "rgba(255,255,255,0.04)" }}
            content={(props) => {
              const p = props as TooltipProps;
              const sum = (p.payload ?? []).reduce((acc, e) => acc + Number(e.value ?? 0), 0);
              return (
                <ChartTooltip
                  {...p}
                  payload={[...(p.payload ?? [])].reverse()}
                  formatValue={formatValue}
                  formatLabel={formatLongDay}
                  total={formatValue(sum)}
                />
              );
            }}
          />
          <Legend verticalAlign="top" align="right" content={() => <LegendContent series={series} />} />
          {series.map((s) => (
            <Bar
              key={s.key}
              dataKey={s.key}
              name={s.label}
              stackId="stack"
              fill={s.color}
              stroke={SURFACE}
              strokeWidth={1}
              maxBarSize={28}
              isAnimationActive={false}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export type BarItem = { key: string; label: string; value: number };

/** A breakdown as horizontal bars, one hue (the bars share one identity), largest first. */
export function HorizontalBars({
  items,
  color = SERIES[0],
  formatValue,
  label,
  valueName,
}: {
  items: BarItem[];
  color?: string;
  formatValue: (value: number) => string;
  label: string;
  valueName: string;
}) {
  const height = Math.max(120, items.length * 36 + 16);
  return (
    <div role="img" aria-label={label} style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={items}
          layout="vertical"
          margin={{ top: 0, right: 40, bottom: 0, left: 0 }}
          barCategoryGap={8}
        >
          <XAxis type="number" hide allowDecimals={false} />
          <YAxis
            type="category"
            dataKey="label"
            tick={{ ...AXIS, fill: "#EEECE7" }}
            axisLine={false}
            tickLine={false}
            width={132}
          />
          <Tooltip
            cursor={{ fill: "rgba(255,255,255,0.04)" }}
            content={(props) => <ChartTooltip {...(props as TooltipProps)} formatValue={formatValue} />}
          />
          <Bar
            dataKey="value"
            name={valueName}
            fill={color}
            radius={[0, 4, 4, 0]}
            maxBarSize={20}
            isAnimationActive={false}
            label={{ position: "right", fill: AXIS_TEXT, fontSize: 12, formatter: (v: unknown) => formatValue(Number(v)) }}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Each row split into stacked segments (e.g. action outcomes per action type). */
export function StackedRows<T extends { label: string }>({
  data,
  series,
  label,
}: {
  data: T[];
  series: SeriesSpec[];
  label: string;
}) {
  const height = Math.max(120, data.length * 40 + 48);
  return (
    <div role="img" aria-label={label} style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ top: 0, right: 8, bottom: 0, left: 0 }} barCategoryGap={10}>
          <XAxis type="number" hide allowDecimals={false} />
          <YAxis
            type="category"
            dataKey="label"
            tick={{ ...AXIS, fill: "#EEECE7" }}
            axisLine={false}
            tickLine={false}
            width={132}
          />
          <Tooltip
            cursor={{ fill: "rgba(255,255,255,0.04)" }}
            content={(props) => {
              const p = props as TooltipProps;
              return (
                <ChartTooltip
                  {...p}
                  payload={(p.payload ?? []).filter((e) => Number(e.value) > 0)}
                  formatValue={(v) => String(v)}
                />
              );
            }}
          />
          <Legend verticalAlign="top" align="right" content={() => <LegendContent series={series} />} />
          {series.map((s) => (
            <Bar
              key={s.key}
              dataKey={s.key}
              name={s.label}
              stackId="row"
              fill={s.color}
              stroke={SURFACE}
              strokeWidth={1}
              maxBarSize={20}
              isAnimationActive={false}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
