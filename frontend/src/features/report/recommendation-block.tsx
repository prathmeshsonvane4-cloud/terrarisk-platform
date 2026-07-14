import type { components } from "@/lib/api/schema";

import { buildRecommendation } from "./recommendation";

type ReportResponse = components["schemas"]["ReportResponse"];

/**
 * Assessment Summary / Primary Drivers / Recommended Action (Product
 * Design v2 §1.1 P7 "Decision Support"). Every line is deterministic —
 * see recommendation.ts — nothing here is generated per-request.
 */
export function RecommendationBlock({ report }: { report: ReportResponse }) {
  const rec = buildRecommendation(report);

  return (
    <section className="flex flex-col gap-4 rounded-lg border p-5">
      <div>
        <h2 className="mb-1 text-xs font-medium tracking-wide text-muted-foreground uppercase">
          Assessment summary
        </h2>
        <p className="text-sm leading-relaxed">{rec.summary}</p>
      </div>

      <div>
        <h2 className="mb-1 text-xs font-medium tracking-wide text-muted-foreground uppercase">
          Primary drivers
        </h2>
        {rec.primaryDrivers.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No factor scored High or Very High risk for this farm.
          </p>
        ) : (
          <ul className="flex flex-col gap-1.5">
            {rec.primaryDrivers.map((driver) => (
              <li key={driver.factor} className="text-sm">
                <span className="font-medium">
                  {driver.label} ({Math.round(driver.value)}/100)
                </span>
                <span className="text-muted-foreground"> — {driver.text}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div>
        <h2 className="mb-1 text-xs font-medium tracking-wide text-muted-foreground uppercase">
          Recommended action
        </h2>
        <p className={`text-sm font-medium ${rec.isIndicativeOnly ? "text-amber-700" : ""}`}>{rec.action}</p>
        <p className="mt-1 text-xs text-muted-foreground">
          Decision support only — the credit decision remains with the bank.
        </p>
      </div>
    </section>
  );
}
