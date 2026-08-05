"use client";

import { Combobox } from "@base-ui/react/combobox";
import { Check, ChevronsUpDown } from "lucide-react";

import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

import type { AdminBoundarySummary } from "./use-admin-boundary-children";

interface VillageOption {
  value: string;
  label: string;
}

interface VillageComboboxProps {
  options: AdminBoundarySummary[] | undefined;
  value: string | null;
  isLoading: boolean;
  disabled: boolean;
  onChange: (id: string) => void;
  placeholder: string;
}

/**
 * Type-to-filter village picker.
 *
 * The other three levels stay plain `<select>`s because they are short
 * (3 states, 1 district, 7 talukas). Village is not: replacing the
 * synthetic square dataset with real Census boundaries took Raichur from
 * 542 to 864 villages, and Devadurga taluk alone now lists **185** — the
 * exact taluk WELL Labs ran its community-hydrology workshop in. A flat
 * 185-option dropdown with no search made the most-used taluk the
 * hardest to navigate, so better data made this control worse; this
 * fixes that, and only that.
 *
 * Built on the Base UI combobox already in the dependency tree rather
 * than a new package, so filtering, keyboard navigation (arrows, Enter,
 * Escape, Home/End), focus management and the ARIA combobox roles are
 * the library's tested behaviour, not hand-rolled here.
 */
export function VillageCombobox({ options, value, isLoading, disabled, onChange, placeholder }: VillageComboboxProps) {
  const isDisabled = disabled || isLoading;
  const items: VillageOption[] = (options ?? []).map((option) => ({ value: option.id, label: option.name }));
  const selected = items.find((item) => item.value === value) ?? null;

  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor="select-area-village">Village</Label>
      <Combobox.Root
        items={items}
        value={selected}
        onValueChange={(next: VillageOption | null) => onChange(next?.value ?? "")}
        disabled={isDisabled}
      >
        <div className="relative">
          <Combobox.Input
            id="select-area-village"
            placeholder={isLoading ? "Loading…" : placeholder}
            className={cn(
              "h-9 w-full rounded-lg border bg-background px-2.5 pr-8 text-sm",
              "focus-visible:ring-ring/50 focus-visible:border-ring focus-visible:ring-[3px] focus-visible:outline-none",
              isDisabled && "cursor-not-allowed opacity-60",
            )}
          />
          <Combobox.Trigger
            aria-label="Show villages"
            disabled={isDisabled}
            className="absolute inset-y-0 right-0 flex w-8 items-center justify-center text-muted-foreground disabled:opacity-60"
          >
            <ChevronsUpDown aria-hidden className="size-4" />
          </Combobox.Trigger>
        </div>

        <Combobox.Portal>
          <Combobox.Positioner sideOffset={4} className="z-50">
            <Combobox.Popup className="max-h-64 w-[var(--anchor-width)] overflow-y-auto rounded-lg border bg-background p-1 shadow-md">
              <Combobox.Empty className="px-2 py-3 text-sm text-muted-foreground">
                No village matches that name.
              </Combobox.Empty>
              <Combobox.List>
                {(item: VillageOption) => (
                  <Combobox.Item
                    key={item.value}
                    value={item}
                    className={cn(
                      "flex cursor-default items-center justify-between gap-2 rounded-md px-2 py-1.5 text-sm",
                      "data-[highlighted]:bg-muted data-[selected]:font-medium",
                    )}
                  >
                    {item.label}
                    <Combobox.ItemIndicator>
                      <Check aria-hidden className="size-4" />
                    </Combobox.ItemIndicator>
                  </Combobox.Item>
                )}
              </Combobox.List>
            </Combobox.Popup>
          </Combobox.Positioner>
        </Combobox.Portal>
      </Combobox.Root>
    </div>
  );
}
