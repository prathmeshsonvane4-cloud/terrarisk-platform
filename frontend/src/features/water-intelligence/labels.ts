import type { components } from "@/lib/api/schema";

export const DELINEATION_METHOD_LABELS: Record<components["schemas"]["DelineationMethod"], string> = {
  manual: "Hand-drawn",
  upload: "Uploaded file",
  auto_dem: "Auto-delineated (DEM)",
};
