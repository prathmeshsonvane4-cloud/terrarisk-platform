/**
 * Map basemap configuration. Esri World Imagery is the approved M2A demo
 * basemap (docs/DECISIONS.md): free with attribution for dev/demo use,
 * licensing review required before commercial deployment. Env-swappable
 * so changing provider is a config change, not a code change.
 */
export const MAP_TILE_URL =
  process.env.NEXT_PUBLIC_MAP_TILE_URL ??
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";

export const MAP_TILE_ATTRIBUTION =
  "Powered by Esri — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community";

// Esri World Imagery serves up to z19 in most of the world; z18 is the
// safe global floor and plenty for field-scale drawing (~0.6m/px).
export const MAP_MAX_ZOOM = 18;
