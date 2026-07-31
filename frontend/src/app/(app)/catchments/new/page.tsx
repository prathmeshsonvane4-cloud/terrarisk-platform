"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { InlineErrorState } from "@/components/ui/error-state";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { CatchmentMap } from "@/features/water-intelligence/catchment-map";
import { CascadingBoundaryPicker } from "@/features/water-intelligence/select-area/cascading-boundary-picker";
import { useAdminBoundaryDetail } from "@/features/water-intelligence/select-area/use-admin-boundary-detail";
import type { AdminBoundarySummary } from "@/features/water-intelligence/select-area/use-admin-boundary-children";
import { VillageBoundaryPreview } from "@/features/water-intelligence/select-area/village-boundary-preview";
import { useCreateCatchment } from "@/features/water-intelligence/use-create-catchment";
import { useUploadCatchment } from "@/features/water-intelligence/use-upload-catchment";
import {
  catchmentAreaBoundsIssue,
  ringAreaHectares,
  toCatchmentGeometry,
  type CatchmentGeometry,
  type Ring,
} from "@/lib/catchment-geo";
import { formatArea } from "@/lib/format";
import { cn } from "@/lib/utils";

type SourceMode = "draw" | "upload" | "select-area";
type SelectAreaChoice = "village" | "draw-inside" | null;

const ACCEPTED_UPLOAD_EXTENSIONS = ".geojson,.json,.kml,.zip";

/**
 * New catchment — combines M4-003's manual-draw path, M4-004's upload
 * path, and Select Area (docs/WELL_Labs_Service2_Strategic_Enhancement_2026.md
 * Part 4) behind one toggle, mirroring assessment-wizard.tsx's two-region
 * layout (persistent map + step-content aside) but as a single step, not
 * a multi-step wizard.
 */
export default function NewCatchmentPage() {
  const router = useRouter();
  const [sourceMode, setSourceMode] = useState<SourceMode>("draw");
  const [name, setName] = useState("");
  const [ring, setRing] = useState<Ring | null>(null);
  const [ringComplete, setRingComplete] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [selectedVillage, setSelectedVillage] = useState<AdminBoundarySummary | null>(null);
  const [selectAreaChoice, setSelectAreaChoice] = useState<SelectAreaChoice>(null);

  const villageDetail = useAdminBoundaryDetail(selectedVillage?.id ?? null);

  const createCatchment = useCreateCatchment();
  const uploadCatchment = useUploadCatchment();
  const isSubmitting = createCatchment.isPending || uploadCatchment.isPending;
  const submitError = createCatchment.error ?? uploadCatchment.error;

  const isDrawingRing = sourceMode === "draw" || (sourceMode === "select-area" && selectAreaChoice === "draw-inside");
  const previewAreaHa = isDrawingRing && ring && ring.length >= 3 ? ringAreaHectares(ring) : null;
  const areaIssue = previewAreaHa !== null ? catchmentAreaBoundsIssue(previewAreaHa) : null;

  const canSubmit =
    name.trim().length > 0 &&
    !isSubmitting &&
    (sourceMode === "draw"
      ? Boolean(ring && ringComplete && !areaIssue)
      : sourceMode === "upload"
        ? Boolean(file)
        : selectAreaChoice === "village"
          ? Boolean(villageDetail.data)
          : selectAreaChoice === "draw-inside"
            ? Boolean(ring && ringComplete && !areaIssue)
            : false);

  function handlePolygonChange(nextRing: Ring | null, complete: boolean) {
    setRing(nextRing);
    setRingComplete(complete);
  }

  function switchMode(mode: SourceMode) {
    if (mode === sourceMode) return;
    setSourceMode(mode);
    setRing(null);
    setRingComplete(false);
    setFile(null);
    setSelectedVillage(null);
    setSelectAreaChoice(null);
  }

  function handleVillageSelect(village: AdminBoundarySummary | null) {
    setSelectedVillage(village);
    setSelectAreaChoice(null);
    setRing(null);
    setRingComplete(false);
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
      return;
    }
    if (sourceMode === "select-area" && selectedVillage) {
      const geometry =
        selectAreaChoice === "village" && villageDetail.data
          ? (villageDetail.data.geometry as unknown as CatchmentGeometry)
          : selectAreaChoice === "draw-inside" && ring
            ? toCatchmentGeometry(ring)
            : null;
      if (!geometry) return;
      createCatchment.mutate(
        { name: name.trim(), geometry, adminBoundaryId: selectedVillage.id },
        { onSuccess: (catchment) => router.push(`/catchments/${catchment.id}`) },
      );
    }
  }

  const villageGeometry = (villageDetail.data?.geometry as GeoJSON.Geometry | undefined) ?? null;

  return (
    <div className="flex flex-1 flex-col md:flex-row">
      <div className="relative h-72 shrink-0 md:h-auto md:flex-1">
        {sourceMode === "draw" && (
          <CatchmentMap
            hasPolygon={Boolean(ring)}
            onPolygonChange={handlePolygonChange}
            locked={isSubmitting}
            className="absolute inset-0"
          />
        )}
        {sourceMode === "upload" && (
          <div className="flex h-full items-center justify-center bg-muted/30 p-6 text-center text-sm text-muted-foreground">
            {file
              ? `${file.name} selected — the parsed boundary will be validated on submit.`
              : "Choose a boundary file to upload."}
          </div>
        )}
        {sourceMode === "select-area" &&
          (selectAreaChoice === "draw-inside" ? (
            <CatchmentMap
              hasPolygon={Boolean(ring)}
              onPolygonChange={handlePolygonChange}
              locked={isSubmitting}
              referenceGeometry={villageGeometry}
              className="absolute inset-0"
            />
          ) : (
            <VillageBoundaryPreview geometry={villageGeometry} className="absolute inset-0" />
          ))}
      </div>

      <aside className="flex w-full flex-col gap-4 border-t p-4 md:w-80 md:border-t-0 md:border-l md:p-6">
        <div>
          <h1 className="text-lg font-semibold">New catchment</h1>
          <p className="text-sm text-muted-foreground">
            A catchment is the boundary TerraRisk generates water reports for — a village, a farm, or any area you
            draw.
          </p>
        </div>

        <div className="flex gap-1 rounded-lg border p-1">
          <button
            type="button"
            onClick={() => switchMode("draw")}
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
            onClick={() => switchMode("upload")}
            disabled={isSubmitting}
            className={cn(
              "flex-1 rounded-md px-2 py-1.5 text-sm font-medium transition-colors",
              sourceMode === "upload" ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-muted",
            )}
          >
            Upload
          </button>
          <button
            type="button"
            onClick={() => switchMode("select-area")}
            disabled={isSubmitting}
            className={cn(
              "flex-1 rounded-md px-2 py-1.5 text-sm font-medium transition-colors",
              sourceMode === "select-area" ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-muted",
            )}
          >
            Select Area
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

          {isDrawingRing && (
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

          {sourceMode === "select-area" && (
            <div className="flex flex-col gap-4">
              <CascadingBoundaryPicker onVillageSelect={handleVillageSelect} disabled={isSubmitting} />

              {selectedVillage && villageDetail.isFetching && (
                <p className="text-sm text-muted-foreground">Loading boundary…</p>
              )}

              {selectedVillage && villageDetail.data && (
                <div className="flex flex-col gap-2 rounded-lg border p-3 text-sm">
                  <p className="font-medium">{villageDetail.data.village ?? villageDetail.data.name}</p>
                  <p className="text-muted-foreground">
                    {[villageDetail.data.taluka, villageDetail.data.district, villageDetail.data.state]
                      .filter(Boolean)
                      .join(", ")}
                  </p>
                  <p className="text-muted-foreground">Area: {formatArea(villageDetail.data.area_ha)}</p>

                  {selectAreaChoice === null && (
                    <div className="flex gap-2 pt-1">
                      <Button
                        type="button"
                        size="sm"
                        onClick={() => setSelectAreaChoice("village")}
                        disabled={isSubmitting}
                      >
                        Use entire village
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() => setSelectAreaChoice("draw-inside")}
                        disabled={isSubmitting}
                      >
                        Draw inside village
                      </Button>
                    </div>
                  )}

                  {selectAreaChoice === "draw-inside" && (
                    <p className="text-xs text-muted-foreground">
                      Draw your boundary on the map — the green village outline is a reference only and isn&rsquo;t
                      enforced.{" "}
                      <button
                        type="button"
                        onClick={() => {
                          setSelectAreaChoice(null);
                          setRing(null);
                          setRingComplete(false);
                        }}
                        className="underline"
                      >
                        Change choice
                      </button>
                    </p>
                  )}
                </div>
              )}
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
