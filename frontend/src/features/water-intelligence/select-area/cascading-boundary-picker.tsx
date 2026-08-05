"use client";

import { useState } from "react";

import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

import { useAdminBoundaryChildren, type AdminBoundarySummary } from "./use-admin-boundary-children";
import { VillageCombobox } from "./village-combobox";

interface CascadingBoundaryPickerProps {
  onVillageSelect: (village: AdminBoundarySummary | null) => void;
  disabled?: boolean;
}

/**
 * State -> District -> Taluka -> Village cascading dropdowns, all four
 * backed by the one generic GET /admin-boundaries?parent_id= endpoint
 * (docs/WELL_Labs_Service2_Strategic_Enhancement_2026.md Part 4).
 * Choosing a level resets every level below it — a district picked under
 * the wrong state is not a state this component ever allows to exist.
 */
export function CascadingBoundaryPicker({ onVillageSelect, disabled = false }: CascadingBoundaryPickerProps) {
  const [stateId, setStateId] = useState<string | null>(null);
  const [districtId, setDistrictId] = useState<string | null>(null);
  const [talukaId, setTalukaId] = useState<string | null>(null);
  const [villageId, setVillageId] = useState<string | null>(null);

  const states = useAdminBoundaryChildren(null);
  const districts = useAdminBoundaryChildren(stateId ?? undefined);
  const talukas = useAdminBoundaryChildren(districtId ?? undefined);
  const villages = useAdminBoundaryChildren(talukaId ?? undefined);

  function handleStateChange(id: string) {
    setStateId(id || null);
    setDistrictId(null);
    setTalukaId(null);
    setVillageId(null);
    onVillageSelect(null);
  }

  function handleDistrictChange(id: string) {
    setDistrictId(id || null);
    setTalukaId(null);
    setVillageId(null);
    onVillageSelect(null);
  }

  function handleTalukaChange(id: string) {
    setTalukaId(id || null);
    setVillageId(null);
    onVillageSelect(null);
  }

  function handleVillageChange(id: string) {
    setVillageId(id || null);
    const village = villages.data?.find((row) => row.id === id) ?? null;
    onVillageSelect(village);
  }

  return (
    <div className="flex flex-col gap-3">
      <BoundarySelect
        label="State"
        value={stateId}
        options={states.data}
        isLoading={states.isFetching}
        disabled={disabled}
        onChange={handleStateChange}
        placeholder="Select a state…"
      />
      <BoundarySelect
        label="District"
        value={districtId}
        options={districts.data}
        isLoading={districts.isFetching}
        disabled={disabled || !stateId}
        onChange={handleDistrictChange}
        placeholder={stateId ? "Select a district…" : "Select a state first"}
      />
      <BoundarySelect
        label="Taluka"
        value={talukaId}
        options={talukas.data}
        isLoading={talukas.isFetching}
        disabled={disabled || !districtId}
        onChange={handleTalukaChange}
        placeholder={districtId ? "Select a taluka…" : "Select a district first"}
      />
      {/* Village is a combobox, not a select — see VillageCombobox for
          why this one level differs (185 villages in Devadurga alone). */}
      <VillageCombobox
        value={villageId}
        options={villages.data}
        isLoading={villages.isFetching}
        disabled={disabled || !talukaId}
        onChange={handleVillageChange}
        placeholder={talukaId ? "Search villages…" : "Select a taluka first"}
      />
    </div>
  );
}

interface BoundarySelectProps {
  label: string;
  value: string | null;
  options: AdminBoundarySummary[] | undefined;
  isLoading: boolean;
  disabled: boolean;
  onChange: (id: string) => void;
  placeholder: string;
}

function BoundarySelect({ label, value, options, isLoading, disabled, onChange, placeholder }: BoundarySelectProps) {
  const isDisabled = disabled || isLoading;
  const id = `select-area-${label.toLowerCase()}`;
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <select
        id={id}
        value={value ?? ""}
        disabled={isDisabled}
        onChange={(event) => onChange(event.target.value)}
        className={cn(
          "h-9 rounded-lg border bg-background px-2.5 text-sm",
          isDisabled && "cursor-not-allowed opacity-60",
        )}
      >
        <option value="">{isLoading ? "Loading…" : placeholder}</option>
        {options?.map((option) => (
          <option key={option.id} value={option.id}>
            {option.name}
          </option>
        ))}
      </select>
    </div>
  );
}
