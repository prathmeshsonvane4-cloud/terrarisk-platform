"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ValueType } from "recharts/types/component/DefaultTooltipContent";

import type { components } from "@/lib/api/schema";

type ObservationPoint = components["schemas"]["ObservationPoint"];

// Hues validated with the dataviz palette checker against the light
// surface (lightness band, chroma floor, CVD separation, contrast — all
// pass). One hue per single-series chart; risk-band status colors are
// never used for series.
const SERIES_COLORS = {
  green: "#15803d",
  blue: "#1d4ed8",
} as const;

interface MonthlyTrendChartProps {
  points: ObservationPoint[];
  variant: "line" | "bar";
  color: keyof typeof SERIES_COLORS;
  /** Formatter for tooltip + y-axis values (e.g. NDVI 2dp vs whole mm). */
  formatValue: (value: number) => string;
  ariaLabel: string;
}

function formatMonth(isoDate: string): string {
  const parsed = new Date(`${isoDate}T00:00:00Z`);
  return parsed.toLocaleDateString("en-IN", { month: "short", year: "2-digit", timeZone: "UTC" });
}

export function MonthlyTrendChart({ points, variant, color, formatValue, ariaLabel }: MonthlyTrendChartProps) {
  if (points.length === 0) {
    return (
      <p className="flex h-52 items-center justify-center text-xs text-muted-foreground">
        No usable observations for this period.
      </p>
    );
  }

  const data = points.map((point) => ({ month: formatMonth(point.period_start), value: point.value }));
  const stroke = SERIES_COLORS[color];
  // ~6 labeled ticks across a 36-month series keeps the axis readable.
  const tickInterval = Math.max(0, Math.ceil(data.length / 6) - 1);

  const axisProps = {
    tick: { fontSize: 11, fill: "var(--muted-foreground)" },
    tickLine: false,
    axisLine: false,
  };
  const tooltipProps = {
    formatter: (value: ValueType | undefined) => [formatValue(Number(value ?? 0)), null] as [string, null],
    contentStyle: { fontSize: 12, borderRadius: 8, border: "1px solid var(--border)" },
    cursor: variant === "line" ? { stroke: "var(--border)" } : { fill: "var(--muted)" },
  };

  return (
    <div role="img" aria-label={ariaLabel} className="h-52 w-full">
      <ResponsiveContainer width="100%" height="100%">
        {variant === "line" ? (
          <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
            <CartesianGrid vertical={false} stroke="var(--border)" strokeOpacity={0.5} />
            <XAxis dataKey="month" interval={tickInterval} {...axisProps} />
            <YAxis {...axisProps} tickFormatter={(v: number) => formatValue(v)} width={58} />
            <Tooltip {...tooltipProps} />
            <Line
              type="monotone"
              dataKey="value"
              stroke={stroke}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4 }}
              isAnimationActive={false}
            />
          </LineChart>
        ) : (
          <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -18 }} barCategoryGap={2}>
            <CartesianGrid vertical={false} stroke="var(--border)" strokeOpacity={0.5} />
            <XAxis dataKey="month" interval={tickInterval} {...axisProps} />
            <YAxis {...axisProps} tickFormatter={(v: number) => formatValue(v)} width={58} />
            <Tooltip {...tooltipProps} />
            <Bar dataKey="value" fill={stroke} radius={[2, 2, 0, 0]} isAnimationActive={false} />
          </BarChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}
