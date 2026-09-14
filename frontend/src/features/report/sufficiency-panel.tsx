import type { components } from "@/lib/api/schema";

type ReportResponse = components["schemas"]["ReportResponse"];

const TIER_LABEL: Record<string, string> = {
  low: "Low stakes",
  medium: "Medium stakes",
  high: "High stakes",
};

/**
 * Model confidence and decision sufficiency, shown as two separate things
 * (evidence-aware roadmap, Phase C). Model confidence says how well the
 * estimate is determined by its data; sufficiency says whether that evidence
 * is enough for a decision at each stakes tier, and names every reason it is
 * not. Neither is a recommended action.
 *
 * Assessments computed before these were recorded say so, rather than the
 * panel silently disappearing.
 */
export function SufficiencyPanel({ report }: { report: ReportResponse }) {
  const { model_confidence: confidence, decision_sufficiency: sufficiency } = report;

  if (!confidence || !sufficiency) {
    return (
      <section className="rounded-lg border p-5 print:break-inside-avoid">
        <h2 className="text-sm font-medium">Model confidence and evidence sufficiency</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          Not recorded for this assessment: it was computed before model confidence and evidence sufficiency were
          assessed separately. Run a new assessment to see them.
        </p>
      </section>
    );
  }

  return (
    <section className="flex flex-col gap-4 rounded-lg border p-5 print:break-inside-avoid">
      <div>
        <h2 className="text-sm font-medium">Model confidence</h2>
        <p className="text-xs text-muted-foreground">How well the estimate is determined by the data it used</p>
        <p className="mt-2 text-sm leading-relaxed">{confidence.statement}</p>
      </div>

      <div className="border-t pt-4">
        <h2 className="text-sm font-medium">Evidence sufficiency</h2>
        <p className="text-xs text-muted-foreground">
          Whether the evidence is enough for a decision — policy {sufficiency.policy_version}, {sufficiency.calibration_status}
        </p>
        <p className="mt-2 text-sm leading-relaxed">{sufficiency.statement}</p>

        <ul className="mt-3 flex flex-col gap-3">
          {sufficiency.tiers.map((verdict) => (
            <li key={verdict.tier} className="rounded-md bg-muted/40 p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-sm font-medium">{TIER_LABEL[verdict.tier] ?? verdict.tier}</span>
                <span
                  className={
                    verdict.sufficient
                      ? "rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-900"
                      : "rounded-full border border-dashed px-2 py-0.5 text-xs font-medium text-muted-foreground"
                  }
                >
                  {verdict.sufficient ? "Sufficient" : "Not sufficient"}
                </span>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">{verdict.description}</p>
              {verdict.inadequacies.length > 0 && (
                <ul className="mt-2 list-disc space-y-1 pl-4 text-xs leading-relaxed">
                  {verdict.inadequacies.map((gap, index) => (
                    <li key={`${gap.code}-${index}`}>{gap.statement}</li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>

        {sufficiency.caveats.length > 0 && (
          <ul className="mt-3 list-disc space-y-1 pl-4 text-xs leading-relaxed text-muted-foreground">
            {sufficiency.caveats.map((caveat) => (
              <li key={caveat.code}>{caveat.statement}</li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
