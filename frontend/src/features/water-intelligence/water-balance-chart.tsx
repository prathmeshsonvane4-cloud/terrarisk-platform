"use client";

import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { ValueType } from "recharts/types/component/DefaultTooltipContent";

// Categorical assignment, fixed order (dataviz skill: "assign
// categorical hues in fixed order, never cycled") — validated via
// scripts/validate_palette.js against this app's chart surface
// (#fcfcfb light / #1a1a19 dark): all four checks pass in both modes
// (worst adjacent normal-vision ΔE 22.9 light / 19.8 dark). Kept as
// flat hex, no separate dark-mode swap, matching
// components/charts/monthly-trend-chart.tsx's own existing precedent
// (its SERIES_COLORS are flat hex too — no chart in this codebase has a
// dark-mode-specific series color yet).
// Exported so generate-water-report-pdf.ts's native water-balance chart
// draws the exact same four hues, not an independently-chosen set —
// one validated palette, two renderers (SVG on screen, vector in the PDF).
export const WATER_BALANCE_BAR_COLORS = {
  rainfall: "#2a78d6",
  et: "#eb6834",
  runoff: "#1baf7a",
  storageChange: "#eda100",
} as const;
const BAR_COLORS = WATER_BALANCE_BAR_COLORS;

interface WaterBalanceChartProps {
  rainfallMm: number | null;
  etMm: number | null;
  runoffMm: number | null;
  storageChangeMm: number | null;
}

/**
 * Single-period water balance breakdown — NOT a monthly time series:
 * GET /catchments/{id}/water-reports returns one aggregate mm total per
 * term for the whole reporting period (WaterBalanceResultResponse has
 * no monthly series field, and no SatelliteObservation-style cache
 * exists for water intelligence yet — water_report_generator.py's own
 * architecture-decision docstring names this gap explicitly). A
 * fabricated monthly series would be exactly the "fake progress/demo
 * data" this product never ships, so this renders the four real
 * aggregate terms as a labeled categorical comparison instead — still a
 * real chart of real numbers, just not the per-month trend a reader
 * might expect from "chart."
 */
export function WaterBalanceChart({ rainfallMm, etMm, runoffMm, storageChangeMm }: WaterBalanceChartProps) {
  const terms: { term: string; value: number | null; color: string }[] = [
    { term: "Rainfall", value: rainfallMm, color: BAR_COLORS.rainfall },
    { term: "ET", value: etMm, color: BAR_COLORS.et },
    { term: "Runoff", value: runoffMm, color: BAR_COLORS.runoff },
    { term: "Storage change", value: storageChangeMm, color: BAR_COLORS.storageChange },
  ];
  const data = terms.filter(
    (entry): entry is { term: string; value: number; color: string } => entry.value !== null,
  );

  if (data.length === 0) {
    return (
      <p className="flex h-52 items-center justify-center text-xs text-muted-foreground">
        No usable water balance figures for this period.
      </p>
    );
  }

  const axisProps = {
    tick: { fontSize: 11, fill: "var(--muted-foreground)" },
    tickLine: false,
    axisLine: false,
  };

  return (
    <div role="img" aria-label="Water balance terms for this reporting period, in millimetres" className="h-52 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
          <CartesianGrid vertical={false} stroke="var(--border)" strokeOpacity={0.5} />
          <XAxis dataKey="term" {...axisProps} />
          <YAxis {...axisProps} tickFormatter={(v: number) => `${Math.round(v)}`} width={58} />
          <Tooltip
            formatter={(value: ValueType | undefined) => [`${Number(value ?? 0).toFixed(1)} mm`, null] as [string, null]}
            contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid var(--border)" }}
            cursor={{ fill: "var(--muted)" }}
          />
          <Bar dataKey="value" radius={[2, 2, 0, 0]} isAnimationActive={false}>
            {data.map((entry) => (
              <Cell key={entry.term} fill={entry.color} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
