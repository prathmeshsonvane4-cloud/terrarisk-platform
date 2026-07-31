import { cn } from "@/lib/utils";

import type { Recommendation, RecommendationSeverity } from "./recommendations";

const SEVERITY_STYLES: Record<RecommendationSeverity, { label: string; chipClass: string }> = {
  high: { label: "High priority", chipClass: "bg-red-100 text-red-900" },
  medium: { label: "Medium priority", chipClass: "bg-amber-100 text-amber-900" },
  low: { label: "Low priority", chipClass: "bg-sky-100 text-sky-900" },
  info: { label: "On track", chipClass: "bg-emerald-100 text-emerald-900" },
};

interface RecommendationCardProps {
  recommendation: Recommendation;
}

/**
 * Renders one recommendation with all four required parts always
 * present — why, evidence, confidence, action (the mission's own rule:
 * "Never output only a score. Always output an actionable
 * recommendation.") — never just a severity chip and a title.
 */
export function RecommendationCard({ recommendation }: RecommendationCardProps) {
  const style = SEVERITY_STYLES[recommendation.severity];
  return (
    <div className="flex flex-col gap-2 rounded-lg border p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap", style.chipClass)}>
          {style.label}
        </span>
        <p className="font-medium">{recommendation.title}</p>
      </div>
      <dl className="flex flex-col gap-1.5">
        <div>
          <dt className="text-xs font-medium text-muted-foreground">Why</dt>
          <dd>{recommendation.why}</dd>
        </div>
        <div>
          <dt className="text-xs font-medium text-muted-foreground">Satellite evidence</dt>
          <dd className="text-muted-foreground">{recommendation.evidence}</dd>
        </div>
        <div>
          <dt className="text-xs font-medium text-muted-foreground">Confidence</dt>
          <dd className="text-muted-foreground">{recommendation.confidence}</dd>
        </div>
        <div>
          <dt className="text-xs font-medium text-muted-foreground">Recommended action</dt>
          <dd className="font-medium">{recommendation.action}</dd>
        </div>
      </dl>
    </div>
  );
}
