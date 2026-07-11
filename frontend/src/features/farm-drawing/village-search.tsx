"use client";

import { useState } from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import type { Village } from "./types";
import { useVillageSearch } from "./use-village-search";

interface VillageSearchProps {
  onSelect: (village: Village) => void;
}

export function VillageSearch({ onSelect }: VillageSearchProps) {
  const [query, setQuery] = useState("");
  const { data: results, isFetching, isError, error, isQueryTooShort } = useVillageSearch(query);

  const hasResults = !!results && results.length > 0;
  const showEmptyState = !isFetching && !isError && !!results && results.length === 0;

  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor="village-search">Search village</Label>
      <Input
        id="village-search"
        placeholder="Type a village name…"
        autoComplete="off"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />

      {isQueryTooShort && (
        <p className="text-xs text-muted-foreground">Keep typing — at least 2 characters.</p>
      )}
      {isFetching && <p className="text-xs text-muted-foreground">Searching…</p>}
      {isError && <p className="text-xs text-destructive">{error.message}</p>}
      {showEmptyState && (
        <p className="text-xs text-muted-foreground">No villages found — check the spelling.</p>
      )}

      {hasResults && (
        <ul className="flex flex-col overflow-hidden rounded-lg ring-1 ring-foreground/10">
          {results.map((village) => (
            <li key={village.id}>
              <button
                type="button"
                onClick={() => onSelect(village)}
                className="flex w-full flex-col gap-0.5 px-3 py-2 text-left text-sm transition-colors hover:bg-muted"
              >
                <span className="font-medium">{village.name}</span>
                <span className="text-xs text-muted-foreground">
                  {village.taluka}, {village.district}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
