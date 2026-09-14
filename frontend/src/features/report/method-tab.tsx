import { RiskBandChip } from "@/components/ui/risk-band-chip";
import type { components } from "@/lib/api/schema";
import { BAND_THRESHOLDS } from "@/lib/band-thresholds";
import { RISK_BANDS } from "@/lib/risk-bands";

import { FACTOR_LABELS, type RiskFactorName } from "./drivers";
import { FACTOR_ORDER } from "./factor-order";

type ReportResponse = components["schemas"]["ReportResponse"];

const FACTOR_DEFINITIONS: Record<RiskFactorName, string> = {
  vegetation_stability:
    "How this farm's current vegetation health compares to its own three-year Sentinel-2 NDVI history — a percentile rank, not a comparison to other farms. A low percentile means the current growing season is markedly worse than this same land has shown before.",
  water_availability:
    "Surface-water (MNDWI) and crop-moisture (NDMI) index readings compared against this farm's own historical range, combined with how recent rainfall compares to the long-term seasonal normal.",
  drought_risk:
    "A Vegetation Condition Index (0 = the driest year observed on this farm, 100 = the best) combined with how recent rainfall compares to the long-term seasonal normal — the approved SPI-style seasonal anomaly.",
  flood_exposure:
    "Historical surface-water occurrence on this exact land parcel (JRC Global Surface Water record, 1984–2021) combined with recent rainfall relative to the seasonal normal.",
};

const ASSUMPTIONS_AND_LIMITATIONS = [
  "Monthly compositing can hide events shorter than a month — a brief dry spell inside an otherwise normal month will not stand out on its own.",
  "Cloud cover reduces how many months are usable for the three optical indices; a low confidence score reflects data availability, not higher risk.",
  "CHIRPS rainfall data publishes with a lag of several weeks — the most recent month in the window may be unavailable and is skipped rather than estimated.",
  "The farm boundary is as drawn by the officer; boundary accuracy is the officer's responsibility, not something this assessment can verify.",
  "This score is decision support for the lending officer. The credit decision remains with the bank.",
];

function formatWeight(weight: number): string {
  return `${Math.round(weight * 100)}%`;
}

/**
 * The Method tab (Product Design v2 §7.5) — answers "why this score":
 * score anatomy (weight → contribution → composite, honest about the
 * floor rule when it fired), band thresholds, factor definitions, and
 * assumptions & limitations. Every number comes from the report payload;
 * the arithmetic shown is display-only recombination of already-computed
 * values — RiskEngine.compute() remains the only place a score is decided.
 */
export function MethodTab({ report }: { report: ReportResponse }) {
  const { method } = report;
  const orderedFactors = FACTOR_ORDER.map((name) => report.factors.find((f) => f.factor === name)).filter(
    (f) => f !== undefined,
  );

  // Uncomputed factors are excluded from the composite (rule-engine-v2), so
  // each computed factor's EFFECTIVE weight is its weight over the weight of
  // the computed factors — the only arithmetic that sums to the composite.
  const computed = orderedFactors.filter((f): f is typeof f & { value: number } => f.value !== null);
  const notComputed = orderedFactors.filter((f) => f.value === null);
  const computedWeight = computed.reduce((sum, f) => sum + (method.weights[f.factor] ?? 0), 0);
  const contributions = computed.map((factor) => {
    const weight = computedWeight > 0 ? (method.weights[factor.factor] ?? 0) / computedWeight : 0;
    return { factor, weight, contribution: factor.value * weight };
  });
  const maxContribution = Math.max(1, ...contributions.map((c) => c.contribution));

  const floorRuleApplied =
    report.overall_score !== null &&
    method.weighted_average_score !== null &&
    Math.abs(method.weighted_average_score - report.overall_score) > 0.01;

  return (
    <div className="flex flex-col gap-4">
      <section className="rounded-lg border p-4">
        <h3 className="text-sm font-medium">Score anatomy</h3>
        <p className="mt-1 text-xs text-muted-foreground">
          Weights version {method.weights_version_id.slice(0, 8)} · effective{" "}
          {new Date(method.weights_effective_from).toLocaleDateString("en-IN", { dateStyle: "medium" })}
        </p>
        <div className="mt-3 flex flex-col gap-3 sm:gap-2">
          {contributions.map(({ factor, weight, contribution }) => (
            <div key={factor.factor} className="flex flex-col gap-1 text-sm sm:flex-row sm:items-center sm:gap-3">
              <div className="flex items-center justify-between gap-2 sm:contents">
                <span className="sm:w-36 sm:shrink-0">{FACTOR_LABELS[factor.factor]}</span>
                <span className="shrink-0 tabular-nums text-muted-foreground sm:w-20">
                  {Math.round(factor.value)} × {formatWeight(weight)}
                </span>
              </div>
              <div className="flex items-center gap-2 sm:contents">
                <span className="flex-1">
                  <span
                    className="block h-3 rounded-sm bg-primary/70"
                    style={{ width: `${(contribution / maxContribution) * 100}%` }}
                  />
                </span>
                <span className="w-12 shrink-0 text-right tabular-nums">{contribution.toFixed(1)}</span>
              </div>
            </div>
          ))}
          {notComputed.map((factor) => (
            <div key={factor.factor} className="flex items-center justify-between gap-2 text-sm text-muted-foreground">
              <span className="sm:w-36 sm:shrink-0">{FACTOR_LABELS[factor.factor]}</span>
              <span className="text-xs">Not computed — excluded from the composite</span>
            </div>
          ))}
        </div>
        {notComputed.length > 0 && computed.length > 0 && (
          <p className="mt-2 text-xs text-muted-foreground">
            Weights are shown re-normalised over the computed factors ({formatWeight(computedWeight)} of the configured
            weight).
          </p>
        )}
        {floorRuleApplied && (
          <>
            <div className="mt-3 flex items-center justify-between border-t pt-2 text-sm font-medium">
              <span>Weighted average (before the floor rule)</span>
              <span className="tabular-nums">{method.weighted_average_score!.toFixed(1)} / 100</span>
            </div>
            <div className="mt-2 rounded-md bg-amber-50 p-3 text-xs text-amber-900">
              <p className="font-medium">Floor rule applied</p>
              <p className="mt-1">
                At least one factor reached the severe threshold ({Math.round(method.floor_threshold)}/100),
                which raises the overall score to at least the High band regardless of the weighted average
                above — the composite score below reflects that floor, not just the four factors&rsquo;
                weighted contribution.
              </p>
            </div>
          </>
        )}
        <div className="mt-3 flex items-center justify-between border-t pt-2 text-sm font-semibold">
          <span>Composite score</span>
          <span className="tabular-nums">
            {report.overall_score === null || report.overall_band === null
              ? "Not estimable"
              : `${Math.round(report.overall_score)} / 100 — ${RISK_BANDS[report.overall_band].label}`}
          </span>
        </div>
        {report.overall_score === null && report.model_confidence && (
          <p className="mt-2 text-xs text-muted-foreground">{report.model_confidence.statement}</p>
        )}
      </section>

      <section className="rounded-lg border p-4">
        <h3 className="text-sm font-medium">Band thresholds</h3>
        <table className="mt-2 w-full text-sm">
          <tbody>
            {BAND_THRESHOLDS.map((entry, index) => {
              const min = index === 0 ? 0 : BAND_THRESHOLDS[index - 1].max + 0.01;
              return (
                <tr key={entry.band} className="border-t first:border-t-0">
                  <td className="py-1.5">
                    <RiskBandChip band={entry.band} showRangeHint={false} />
                  </td>
                  <td className="py-1.5 text-right tabular-nums text-muted-foreground">
                    {min.toFixed(index === 0 ? 0 : 2)} – {entry.max}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>

      <section className="rounded-lg border p-4">
        <h3 className="text-sm font-medium">Factor definitions</h3>
        <dl className="mt-2 flex flex-col gap-3">
          {FACTOR_ORDER.map((name) => (
            <div key={name}>
              <dt className="text-sm font-medium">{FACTOR_LABELS[name]}</dt>
              <dd className="text-sm text-muted-foreground">{FACTOR_DEFINITIONS[name]}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="rounded-lg border p-4">
        <h3 className="text-sm font-medium">Assumptions &amp; limitations</h3>
        <ul className="mt-2 flex list-disc flex-col gap-1.5 pl-4 text-sm text-muted-foreground">
          {ASSUMPTIONS_AND_LIMITATIONS.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </section>
    </div>
  );
}
