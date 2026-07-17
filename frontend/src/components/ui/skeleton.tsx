import * as React from "react";

import { cn } from "@/lib/utils";

/** Base skeleton block — always paired with a layout that matches the real
 * content's shape (P10 requirement 6: "skeletons that match final layout,
 * never a full-screen spinner"). `aria-hidden` since a skeleton conveys no
 * information itself; the loading state's own aria-live text does that. */
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      aria-hidden="true"
      className={cn("animate-pulse rounded-md bg-muted", className)}
      {...props}
    />
  );
}

/** A row-shaped skeleton matching the list rows used across Farms /
 * Reports / Assessments index pages — icon-less two-line card. */
function SkeletonListRow() {
  return (
    <div className="flex flex-col gap-2 rounded-lg border p-3">
      <Skeleton className="h-4 w-1/3" />
      <Skeleton className="h-3 w-1/2" />
    </div>
  );
}

function SkeletonList({ rows = 3 }: { rows?: number }) {
  return (
    <div role="status" aria-label="Loading" className="flex flex-col gap-2">
      {Array.from({ length: rows }).map((_, index) => (
        <SkeletonListRow key={index} />
      ))}
      <span className="sr-only">Loading…</span>
    </div>
  );
}

export { Skeleton, SkeletonListRow, SkeletonList };
