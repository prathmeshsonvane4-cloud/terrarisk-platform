"use client";

import { MapIcon } from "lucide-react";
import Link from "next/link";

import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { RiskBandChip } from "@/components/ui/risk-band-chip";
import { SkeletonList } from "@/components/ui/skeleton";
import { useFarms } from "@/features/workspace/use-farms";
import { formatArea } from "@/lib/format";

/**
 * The Farms workspace index (Product Design v2 §7, screen 7) — every farm
 * the officer owns or shares a branch with, each row already carrying its
 * latest assessment and any in-flight run (GET /farms, M2B P7).
 */
export default function FarmsPage() {
  const { data: farms, isPending, isError, error, refetch } = useFarms();

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-4 p-4 md:p-6">
      <h1 className="text-lg font-semibold">Farms</h1>

      {isPending && <SkeletonList rows={4} />}

      {isError && <ErrorState error={error} onRetry={() => refetch()} />}

      {!isPending && !isError && farms.length === 0 && (
        <EmptyState
          icon={MapIcon}
          title="No farms mapped yet"
          description="Nobody at this branch has mapped a farm boundary yet — once one is, it'll appear here with its assessment history."
          action={{ label: "Map a farm", href: "/assessments/new" }}
        />
      )}

      {!isPending && !isError && farms.length > 0 && (
        <div className="flex flex-col divide-y rounded-lg border">
          {farms.map((farm) => (
            <Link
              key={farm.id}
              href={`/farms/${farm.id}`}
              className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 text-sm hover:bg-muted"
            >
              <div>
                <p className="font-medium">
                  {farm.village_name}
                  <span className="font-normal text-muted-foreground">
                    {" "}
                    · {farm.taluka_name}, {farm.district_name}
                  </span>
                </p>
                <p className="text-xs text-muted-foreground">
                  {formatArea(farm.area_ha)} · Mapped by {farm.officer_name}
                </p>
              </div>
              <div className="flex items-center gap-2">
                {farm.active_job && (
                  <span className="flex items-center gap-1.5 rounded-full border bg-muted/50 px-2 py-0.5 text-xs font-medium">
                    <span aria-hidden className="size-1.5 animate-pulse rounded-full bg-primary" />
                    {farm.active_job.status}
                  </span>
                )}
                {farm.latest_assessment ? (
                  <RiskBandChip
                    band={farm.latest_assessment.overall_band}
                    score={farm.latest_assessment.overall_score}
                  />
                ) : (
                  !farm.active_job && (
                    <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                      Not assessed
                    </span>
                  )
                )}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
