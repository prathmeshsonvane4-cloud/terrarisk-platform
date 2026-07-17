import { RiskBandChip } from "@/components/ui/risk-band-chip";

import { FACTOR_LABELS, factorDriverText, type FactorScore } from "./drivers";

/** One climate factor: score, band chip (label always beside the color),
 * and the plain-language driver line composed from the engine's persisted
 * raw inputs (Blueprint §08: each factor shown with one line explaining
 * what drove it — never just a label). */
export function FactorCard({ factor }: { factor: FactorScore }) {
  return (
    <div className="flex flex-col gap-2 rounded-lg border p-4">
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-medium">{FACTOR_LABELS[factor.factor]}</p>
        <RiskBandChip band={factor.band} />
      </div>
      <p className="text-2xl font-semibold tabular-nums">
        {Math.round(factor.value)}
        <span className="text-sm font-normal text-muted-foreground"> / 100</span>
      </p>
      <p className="text-xs leading-relaxed text-muted-foreground">{factorDriverText(factor)}</p>
    </div>
  );
}
