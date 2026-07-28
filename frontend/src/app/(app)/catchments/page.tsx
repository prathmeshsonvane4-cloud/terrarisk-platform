"use client";

import { Droplets, Plus } from "lucide-react";
import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { SkeletonList } from "@/components/ui/skeleton";
import { DELINEATION_METHOD_LABELS } from "@/features/water-intelligence/labels";
import { useCatchments } from "@/features/water-intelligence/use-catchments";
import { formatArea } from "@/lib/format";
import { cn } from "@/lib/utils";

/** The Catchments workspace index (Water Intelligence, ticket M6-001) —
 * mirrors app/(app)/farms/page.tsx's exact list/empty/error/loading
 * shape (GET /catchments, M4-005). */
export default function CatchmentsPage() {
  const { data: catchments, isPending, isError, error, refetch } = useCatchments();

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-4 p-4 md:p-6">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-lg font-semibold">Catchments</h1>
        <Link href="/catchments/new" className={cn(buttonVariants({ size: "sm" }), "gap-1.5")}>
          <Plus aria-hidden className="size-4" />
          New catchment
        </Link>
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
            <Link
              key={catchment.id}
              href={`/catchments/${catchment.id}`}
              className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 text-sm hover:bg-muted"
            >
              <div>
                <p className="font-medium">{catchment.name}</p>
                <p className="text-xs text-muted-foreground">
                  {formatArea(catchment.area_ha)} · {DELINEATION_METHOD_LABELS[catchment.delineation_method]}
                </p>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
