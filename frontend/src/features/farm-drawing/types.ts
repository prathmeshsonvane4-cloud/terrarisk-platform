import type { components } from "@/lib/api/schema";

// The shape P2 (map) consumes directly — id, name, taluka, district, and
// a centroid to fly the map to. Reused verbatim from the generated schema
// rather than redeclared, so a backend field change fails the frontend
// build instead of silently drifting.
export type Village = components["schemas"]["VillageSearchResult"];
