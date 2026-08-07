"use client";

import type { components } from "@/lib/api/schema";

import { WATER_BALANCE_BAR_COLORS } from "./water-balance-chart";

type AnnualWaterBalance = components["schemas"]["AnnualWaterBalanceResponse"];

/** A water year needs this many months before its totals are comparable
 * with a full year's. Below it the year is a stub at the edge of the
 * observation window, not a dry year — the distinction this whole
 * component exists to preserve. */
const COMPLETE_YEAR_MONTHS = 12;

/**
 * Year-on-year water balance, one bar group per WATER YEAR (June-May).
 *
 * Replaces a chart that plotted one point per report RUN — so generating
 * two reports in an afternoon produced two points both dated today. That
 * was a report-generation log shaped like a time series, and it could not
 * answer the only temporal question a watershed programme acts on: is
 * this catchment gaining or losing water, and is that getting worse.
 *
 * Partial years are drawn faded and labelled with their month count
 * rather than hidden. Hiding them would silently change the period the
 * reader thinks they are looking at; showing them at full strength would
 * invite reading a 2-month stub as a catastrophically dry year. A 3-year
 * observation window typically yields two complete water years and two
 * partial ones at the edges.
 */
export function AnnualWaterBalanceChart({ annual }: { annual: AnnualWaterBalance[] }) {
  if (annual.length === 0) return null;

  // One shared scale across all years and all terms — bars are only
  // comparable between years if they are measured against the same axis.
  const maxValue = Math.max(
    ...annual.flatMap((year) =>
      [year.rainfall_mm, year.et_mm, year.runoff_mm, Math.abs(year.storage_change_mm ?? 0)].map((v) =>
        v === null ? 0 : v,
      ),
    ),
    1,
  );

  const terms = [
    { key: "rainfall_mm", label: "Rainfall", color: WATER_BALANCE_BAR_COLORS.rainfall },
    { key: "et_mm", label: "ET", color: WATER_BALANCE_BAR_COLORS.et },
    { key: "runoff_mm", label: "Runoff", color: WATER_BALANCE_BAR_COLORS.runoff },
    { key: "storage_change_mm", label: "Storage change", color: WATER_BALANCE_BAR_COLORS.storageChange },
  ] as const;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        {terms.map((term) => (
          <span key={term.key} className="inline-flex items-center gap-1.5">
            <span aria-hidden className="inline-block size-2.5 rounded-[2px]" style={{ background: term.color }} />
            {term.label}
          </span>
        ))}
      </div>

      <div className="flex flex-col gap-3">
        {annual.map((year) => {
          const isPartial = year.months_covered < COMPLETE_YEAR_MONTHS;
          return (
            <div key={year.label} className={isPartial ? "opacity-60" : undefined}>
              <div className="mb-1 flex items-baseline justify-between gap-2">
                <span className="text-xs font-medium tabular-nums">{year.label}</span>
                <span className="text-[11px] text-muted-foreground">
                  {isPartial
                    ? `partial — ${year.months_covered} of 12 months`
                    : `${year.storage_change_mm !== null && year.storage_change_mm >= 0 ? "net gain" : "net loss"} ${
                        year.storage_change_mm === null ? "—" : `${Math.round(Math.abs(year.storage_change_mm))} mm`
                      }`}
                </span>
              </div>

              <div className="flex flex-col gap-1">
                {terms.map((term) => {
                  const raw = year[term.key];
                  // Storage change is the one signed term: a loss is a
                  // real result, not missing data, so it is drawn at its
                  // magnitude and named by the label above rather than
                  // being clamped to zero or dropped.
                  const magnitude = raw === null ? 0 : Math.abs(raw);
                  return (
                    <div key={term.key} className="flex items-center gap-2">
                      <div className="h-3 flex-1 overflow-hidden rounded-sm bg-muted">
                        <div
                          className="h-full rounded-sm"
                          style={{ width: `${(magnitude / maxValue) * 100}%`, background: term.color }}
                        />
                      </div>
                      <span className="w-20 shrink-0 text-right text-[11px] tabular-nums text-muted-foreground">
                        {raw === null ? "—" : `${Math.round(raw)} mm`}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>

      <p className="text-xs leading-relaxed text-muted-foreground">
        Water years run June to May, so each row holds one monsoon and the dry season it feeds. A calendar-year split
        would cut every monsoon across two rows. Storage change is the residual of rainfall minus ET minus runoff — it
        also absorbs deep percolation leaving the catchment, so it is not a measurement of recharge.
      </p>
    </div>
  );
}
