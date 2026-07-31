"use client";

import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { ValueType } from "recharts/types/component/DefaultTooltipContent";

export interface TrendPoint {
  generatedAt: string;
  value: number | null;
}

interface MetricTrendChartProps {
  /** Oldest first — callers own the sort, since the history endpoint
   * itself returns newest-first (most useful order for a list; wrong
   * order for a left-to-right chart). */
  points: TrendPoint[];
  color: string;
  ariaLabel: string;
  valueFormatter?: (value: number) => string;
}

const MIN_POINTS_FOR_A_TREND = 2;

/**
 * One metric, one catchment, over its own real report-run history — a
 * genuine time series, unlike WaterBalanceChart's single-period
 * categorical bars (that component's own docstring explains why no
 * monthly series exists per-report; this one exists precisely because
 * water-reports/history now provides real run-over-run points instead).
 *
 * Deliberately single-series: comparing catchments by overlaying their
 * trends on one shared date axis would misrepresent each catchment's own
 * independent report-trigger cadence as if they were synchronized
 * observations. The compare page instead renders one of these per
 * catchment, side by side (small multiples), which is a truer read for
 * an axis (report-run date) each catchment doesn't actually share.
 */
export function MetricTrendChart({ points, color, ariaLabel, valueFormatter }: MetricTrendChartProps) {
  const usablePoints = points.filter((point) => point.value !== null);

  if (usablePoints.length < MIN_POINTS_FOR_A_TREND) {
    return (
      <p className="flex h-32 items-center justify-center text-center text-xs text-muted-foreground">
        Not enough history yet — trigger more water reports over time to see a trend.
      </p>
    );
  }

  const data = points.map((point) => ({
    date: new Date(point.generatedAt).toLocaleDateString("en-IN", { day: "numeric", month: "short" }),
    value: point.value,
  }));

  const axisProps = {
    tick: { fontSize: 11, fill: "var(--muted-foreground)" },
    tickLine: false,
    axisLine: false,
  };

  return (
    <div role="img" aria-label={ariaLabel} className="h-32 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
          <CartesianGrid vertical={false} stroke="var(--border)" strokeOpacity={0.5} />
          <XAxis dataKey="date" {...axisProps} />
          <YAxis {...axisProps} width={58} />
          <Tooltip
            formatter={
              ((value: ValueType | undefined) => [
                valueFormatter ? valueFormatter(Number(value ?? 0)) : `${Number(value ?? 0).toFixed(1)}`,
                null,
              ]) as (value: ValueType | undefined) => [string, null]
            }
            contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid var(--border)" }}
          />
          <Line
            type="monotone"
            dataKey="value"
            stroke={color}
            strokeWidth={2}
            dot={{ r: 3, fill: color }}
            connectNulls={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
