"use client";

import { ClipboardList, Droplets, GitCompare, Plus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { buttonVariants } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { SkeletonList } from "@/components/ui/skeleton";
import { DELINEATION_METHOD_LABELS } from "@/features/water-intelligence/labels";
import { useCatchments } from "@/features/water-intelligence/use-catchments";
import { formatArea } from "@/lib/format";
import { cn } from "@/lib/utils";

const MIN_CATCHMENTS_TO_COMPARE = 2;

/** The Catchments workspace index (Water Intelligence, ticket M6-001) —
 * mirrors app/(app)/farms/page.tsx's exact list/empty/error/loading
 * shape (GET /catchments, M4-005). Multi-select + "Compare selected"
 * (docs/WELL_Labs_Raichur_Founder_Review_2026.md Part 4/5) is the one
 * addition: a checkbox per row alongside the existing row-click
 * navigation, not a redesign of the list itself. */
export default function CatchmentsPage() {
  const { data: catchments, isPending, isError, error, refetch } = useCatchments();
  const [selectedIds, setSelectedIds] = useState<string[]>([]);

  function toggleSelected(id: string, checked: boolean) {
    setSelectedIds((current) => (checked ? [...current, id] : current.filter((selected) => selected !== id)));
  }

  const compareHref = `/catchments/compare?ids=${selectedIds.join(",")}`;

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-4 p-4 md:p-6">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold">Catchments</h1>
          <p className="text-sm text-muted-foreground">
            Every village or field boundary TerraRisk is generating water reports for. Select two or more with the
            checkboxes to compare them side by side.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link href="/catchments/priority-queue" className={cn(buttonVariants({ size: "sm", variant: "outline" }), "gap-1.5")}>
            <ClipboardList aria-hidden className="size-4" />
            Priority Queue
          </Link>
          {selectedIds.length >= MIN_CATCHMENTS_TO_COMPARE && (
            <Link href={compareHref} className={cn(buttonVariants({ size: "sm", variant: "outline" }), "gap-1.5")}>
              <GitCompare aria-hidden className="size-4" />
              Compare selected ({selectedIds.length})
            </Link>
          )}
          <Link href="/catchments/new" className={cn(buttonVariants({ size: "sm" }), "gap-1.5")}>
            <Plus aria-hidden className="size-4" />
            New catchment
          </Link>
        </div>
      </header>

      {isPending && <SkeletonList rows={4} />}

      {isError && <ErrorState error={error} onRetry={() => refetch()} />}

      {!isPending && !isError && catchments.length === 0 && (
        <EmptyState
          icon={Droplets}
          title="No catchments mapped yet"
          description="Draw or upload a catchment boundary to start generating water intelligence reports for it."
          action={{ label: "New catchment", href: "/catchments/new" }}
        />
      )}

      {!isPending && !isError && catchments.length > 0 && (
        <div className="flex flex-col divide-y rounded-lg border">
          {catchments.map((catchment) => (
            <div key={catchment.id} className="flex items-center gap-3 px-4 py-3 hover:bg-muted">
              <input
                type="checkbox"
                aria-label={`Select ${catchment.name} to compare`}
                checked={selectedIds.includes(catchment.id)}
                onChange={(event) => toggleSelected(catchment.id, event.target.checked)}
                className="size-4 shrink-0 accent-primary"
              />
              <Link
                href={`/catchments/${catchment.id}`}
                className="flex flex-1 flex-wrap items-center justify-between gap-2 text-sm"
              >
                <div>
                  <p className="font-medium">{catchment.name}</p>
                  <p className="text-xs text-muted-foreground">
                    {formatArea(catchment.area_ha)} · {DELINEATION_METHOD_LABELS[catchment.delineation_method]}
                  </p>
                </div>
              </Link>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
