"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { InlineErrorState } from "@/components/ui/error-state";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { CatchmentMap } from "@/features/water-intelligence/catchment-map";
import { useCreateCatchment } from "@/features/water-intelligence/use-create-catchment";
import { useUploadCatchment } from "@/features/water-intelligence/use-upload-catchment";
import { catchmentAreaBoundsIssue, ringAreaHectares, toCatchmentGeometry, type Ring } from "@/lib/catchment-geo";
import { formatArea } from "@/lib/format";
import { cn } from "@/lib/utils";

type SourceMode = "draw" | "upload";

const ACCEPTED_UPLOAD_EXTENSIONS = ".geojson,.json,.kml,.zip";

/**
 * New catchment — combines M4-003's manual-draw path and M4-004's
 * upload path behind one toggle, mirroring assessment-wizard.tsx's
 * two-region layout (persistent map + step-content aside) but as a
 * single step, not a multi-step wizard: catchments have no
 * village-search step and no draft-persistence requirement the way a
 * farm assessment does, so a stepper would be structure without content.
 */
export default function NewCatchmentPage() {
  const router = useRouter();
  const [sourceMode, setSourceMode] = useState<SourceMode>("draw");
  const [name, setName] = useState("");
  const [ring, setRing] = useState<Ring | null>(null);
  const [ringComplete, setRingComplete] = useState(false);
  const [file, setFile] = useState<File | null>(null);

  const createCatchment = useCreateCatchment();
  const uploadCatchment = useUploadCatchment();
  const isSubmitting = createCatchment.isPending || uploadCatchment.isPending;
  const submitError = createCatchment.error ?? uploadCatchment.error;

  const previewAreaHa = ring && ring.length >= 3 ? ringAreaHectares(ring) : null;
  const areaIssue = previewAreaHa !== null ? catchmentAreaBoundsIssue(previewAreaHa) : null;

  const canSubmit =
    name.trim().length > 0 &&
    !isSubmitting &&
    (sourceMode === "draw" ? Boolean(ring && ringComplete && !areaIssue) : Boolean(file));

  function handlePolygonChange(nextRing: Ring | null, complete: boolean) {
    setRing(nextRing);
    setRingComplete(complete);
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!canSubmit) return;

    if (sourceMode === "draw" && ring) {
      createCatchment.mutate(
        { name: name.trim(), geometry: toCatchmentGeometry(ring) },
        { onSuccess: (catchment) => router.push(`/catchments/${catchment.id}`) },
      );
      return;
    }
    if (sourceMode === "upload" && file) {
      uploadCatchment.mutate(
        { file, name: name.trim() },
        { onSuccess: (catchment) => router.push(`/catchments/${catchment.id}`) },
      );
    }
  }

  return (
    <div className="flex flex-1 flex-col md:flex-row">
      <div className="relative h-72 shrink-0 md:h-auto md:flex-1">
        {sourceMode === "draw" ? (
          <CatchmentMap
            hasPolygon={Boolean(ring)}
            onPolygonChange={handlePolygonChange}
            locked={isSubmitting}
            className="absolute inset-0"
          />
        ) : (
          <div className="flex h-full items-center justify-center bg-muted/30 p-6 text-center text-sm text-muted-foreground">
            {file
              ? `${file.name} selected — the parsed boundary will be validated on submit.`
              : "Choose a boundary file to upload."}
          </div>
        )}
      </div>

      <aside className="flex w-full flex-col gap-4 border-t p-4 md:w-80 md:border-t-0 md:border-l md:p-6">
        <h1 className="text-lg font-semibold">New catchment</h1>

        <div className="flex gap-1 rounded-lg border p-1">
          <button
            type="button"
            onClick={() => setSourceMode("draw")}
            disabled={isSubmitting}
            className={cn(
              "flex-1 rounded-md px-2 py-1.5 text-sm font-medium transition-colors",
              sourceMode === "draw" ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-muted",
            )}
          >
            Draw
          </button>
          <button
            type="button"
            onClick={() => setSourceMode("upload")}
            disabled={isSubmitting}
            className={cn(
              "flex-1 rounded-md px-2 py-1.5 text-sm font-medium transition-colors",
              sourceMode === "upload" ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-muted",
            )}
          >
            Upload
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-1 flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="catchment-name">Name</Label>
            <Input
              id="catchment-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              disabled={isSubmitting}
              required
              maxLength={255}
            />
          </div>

          {sourceMode === "draw" && (
            <div className="flex flex-col gap-1 text-sm">
              {previewAreaHa !== null ? (
                <p className="text-muted-foreground">Preview area: {formatArea(previewAreaHa)}</p>
              ) : (
                <p className="text-muted-foreground">Draw a boundary on the map to continue.</p>
              )}
              {areaIssue && <p className="text-destructive">{areaIssue}</p>}
            </div>
          )}

          {sourceMode === "upload" && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="catchment-file">Boundary file</Label>
              <input
                id="catchment-file"
                type="file"
                accept={ACCEPTED_UPLOAD_EXTENSIONS}
                disabled={isSubmitting}
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                className="rounded-lg border p-2 text-sm file:mr-2 file:rounded-md file:border-0 file:bg-muted file:px-2 file:py-1 file:text-xs file:font-medium"
              />
              <p className="text-xs text-muted-foreground">GeoJSON (.geojson/.json), KML, or a zipped Shapefile (.zip).</p>
            </div>
          )}

          {submitError && <InlineErrorState error={submitError} />}

          <div className="flex-1" />

          <Button type="submit" disabled={!canSubmit}>
            {isSubmitting ? "Saving…" : "Create catchment"}
          </Button>
        </form>
      </aside>
    </div>
  );
}
