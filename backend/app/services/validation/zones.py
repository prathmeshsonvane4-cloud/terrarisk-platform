"""Agro-climatic zones and the plausible ranges each one implies.

A water balance cannot be judged against one global set of bounds. An
ET/P ratio of 0.35 is unremarkable in the Western Ghats and close to
impossible in Marathwada; a runoff coefficient of 0.45 is ordinary in
coastal Kerala and a red flag on the Deccan plateau. Every range below is
therefore keyed to a zone, and a check that cannot establish the zone
says so rather than falling back to a global bound wide enough to pass
anything.

=====================================================================
WHERE THESE NUMBERS COME FROM, AND WHAT THEY ARE NOT
=====================================================================

They are **literature-derived envelopes, not calibrated bounds.** They
mark the edge of what the published record reports for a zone, so that a
value outside them is worth a human look. They are NOT a claim that a
value inside them is correct — a subtly wrong number that lands inside a
wide envelope passes here, and that is an accepted limit of this
approach, not an oversight.

The framing is Budyko's: over a multi-year window, the fraction of
precipitation returned to the atmosphere as actual ET is largely set by
the aridity index (PET/P). As a catchment gets drier, AET/P climbs
toward 1 and the water available for runoff and recharge collapses. For
a semi-arid Deccan catchment at P ~ 550 mm/yr and PET ~ 1,800 mm/yr,
Fu's form of the Budyko curve puts AET/P near 0.95, leaving only a few
percent of rainfall for everything else.

The envelopes below are deliberately WIDER than Budyko alone would give,
in both directions, for three reasons that all apply to Indian
catchments:

1. Budyko describes long-term closed basins. Irrigation imports, canal
   command areas, and inter-catchment subsurface flow all break that
   assumption — and the water balance this validates already assumes a
   closed catchment it cannot verify (Blueprint v2 Part 10, limitation 3).
2. Monsoon rainfall arrives in high-intensity bursts, so observed runoff
   coefficients in Indian semi-arid catchments routinely exceed what an
   annual-average energy-balance argument predicts.
3. A three-year window is not a climatological average. A single failed
   monsoon inside it legitimately moves every ratio.

**These ranges have NOT been reviewed by a domain expert and are not
calibrated against any Indian catchment's measured record.** They are the
author's reading of the published envelope, and every finding derived
from them says so. Narrowing them is a calibration exercise requiring
gauged data; widening one to make a real failure pass would be exactly
the move this harness exists to prevent.

**Upgrade path, named rather than pretended away:** the honest version of
the ET check is Budyko computed per catchment from its own PET, not a
zone-wide envelope. No provider in this codebase fetches PET — see the
audit in `docs/` for the full product inventory — so the zone envelope is
what can be built today. When a PET source exists, `et_fraction` should
become a per-catchment Budyko expectation and these bounds become the
fallback for when it is unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

__all__ = [
    "AgroClimaticZone",
    "ZoneRanges",
    "RANGES_BY_ZONE",
    "classify_zone_by_rainfall",
    "classify_zone_from_normals",
    "ranges_for",
]


class AgroClimaticZone(str, Enum):
    """Coarse moisture regime, sufficient to pick a plausibility envelope.

    Not a substitute for ICAR's 15-zone or the NARP 127-zone
    classification — those encode soil, cropping system and season length
    alongside moisture, none of which this harness uses. Four moisture
    classes plus a coastal case is the resolution these checks can
    actually justify.
    """

    ARID = "arid"
    SEMI_ARID = "semi_arid"
    SUB_HUMID = "sub_humid"
    HUMID = "humid"
    # Deliberately NOT inferable from rainfall — see classify_zone_by_rainfall.
    COASTAL = "coastal"
    # Returned when the zone genuinely cannot be established. Checks that
    # need a zone skip and record why, rather than borrowing a default.
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ZoneRanges:
    """Plausible annual ranges for one zone. All ratios are dimensionless
    fractions of precipitation over the same window; all depths are mm
    per year.

    Bounds are inclusive. A value exactly on a bound passes — these are
    envelope edges read off a literature spread, and treating the last
    digit as decisive would be false precision about a number that is
    itself approximate.
    """

    # Mean annual precipitation the zone is defined over. Used to sanity
    # check that an assigned zone matches the rainfall actually observed.
    rainfall_mm: tuple[float, float]
    # Actual ET as a fraction of precipitation, multi-year.
    et_fraction: tuple[float, float]
    # Runoff as a fraction of precipitation — the runoff coefficient.
    runoff_coefficient: tuple[float, float]
    # |storage change| as a fraction of precipitation. A catchment cannot
    # sustainably gain or lose a large fraction of its rainfall to storage
    # every year; a large residual over a multi-year window is far more
    # often an error in P, ET or Q than a real storage signal. This is the
    # check that catches an upstream defect the individual term checks miss.
    abs_storage_change_fraction: tuple[float, float]
    notes: str = ""


# Rainfall class boundaries follow the conventional Indian usage (arid
# below ~400 mm, semi-arid to ~750, sub-humid to ~1,200, humid above).
# Widely reproduced across Indian agro-meteorological literature; no
# single authority is cited because no single one is universal, and the
# boundaries only select an envelope rather than entering any arithmetic.
_ARID_CEILING_MM = 400.0
_SEMI_ARID_CEILING_MM = 750.0
_SUB_HUMID_CEILING_MM = 1200.0

RANGES_BY_ZONE: dict[AgroClimaticZone, ZoneRanges] = {
    AgroClimaticZone.ARID: ZoneRanges(
        rainfall_mm=(50.0, 450.0),
        # Approaching unity: in an arid catchment essentially all
        # precipitation is returned to the atmosphere.
        et_fraction=(0.75, 1.00),
        runoff_coefficient=(0.00, 0.15),
        abs_storage_change_fraction=(0.00, 0.20),
        notes="Budyko AET/P approaches 1; runoff is episodic and small in the annual mean.",
    ),
    AgroClimaticZone.SEMI_ARID: ZoneRanges(
        rainfall_mm=(350.0, 850.0),
        # Budyko alone would suggest ~0.85-0.95 here. The floor is set
        # well below that to accommodate a canal-irrigated or
        # monsoon-burst-dominated catchment without waving through a
        # value that is merely wrong.
        et_fraction=(0.55, 0.95),
        runoff_coefficient=(0.02, 0.30),
        abs_storage_change_fraction=(0.00, 0.25),
        notes=(
            "Deccan/Marathwada/Raichur sit here. Published runoff coefficients for "
            "semi-arid Deccan catchments cluster around 0.10-0.20; the ceiling is "
            "raised to 0.30 to allow for a high-intensity monsoon year."
        ),
    ),
    AgroClimaticZone.SUB_HUMID: ZoneRanges(
        rainfall_mm=(700.0, 1300.0),
        et_fraction=(0.40, 0.80),
        runoff_coefficient=(0.10, 0.45),
        abs_storage_change_fraction=(0.00, 0.30),
    ),
    AgroClimaticZone.HUMID: ZoneRanges(
        rainfall_mm=(1100.0, 4500.0),
        et_fraction=(0.20, 0.60),
        runoff_coefficient=(0.25, 0.70),
        abs_storage_change_fraction=(0.00, 0.35),
        notes="Energy-limited rather than water-limited: ET is capped by available energy, not supply.",
    ),
    AgroClimaticZone.COASTAL: ZoneRanges(
        rainfall_mm=(700.0, 3500.0),
        et_fraction=(0.25, 0.65),
        runoff_coefficient=(0.20, 0.65),
        abs_storage_change_fraction=(0.00, 0.35),
        notes=(
            "Widest envelope of any zone, and the least trustworthy. Coastal "
            "catchments span an enormous rainfall range, and a shallow saline "
            "water table plus tidal influence break the closed-catchment "
            "assumption more severely than anywhere else."
        ),
    ),
}


def classify_zone_by_rainfall(mean_annual_rainfall_mm: float | None) -> AgroClimaticZone:
    """Assign a moisture zone from long-term mean annual rainfall.

    Rainfall alone, not an aridity index. The correct discriminator is
    P/PET, and this codebase fetches no PET product — so this is a
    documented approximation, not the intended method. It is adequate
    where PET varies little across the deployment area (all of Latur and
    Raichur sit in one PET regime) and degrades where it does not.

    **Never returns COASTAL.** Proximity to a coast is not a rainfall
    property, and inferring it from a rainfall figure would be guessing.
    A coastal catchment must be labelled explicitly by the caller; until
    the platform carries that information, coastal catchments will be
    classified by rainfall alone and validated against a moisture-zone
    envelope that omits the tidal/saline caveats in
    `RANGES_BY_ZONE[COASTAL].notes`. That is a real gap in the harness
    and is recorded as one.
    """
    if mean_annual_rainfall_mm is None or mean_annual_rainfall_mm <= 0:
        return AgroClimaticZone.UNKNOWN
    if mean_annual_rainfall_mm < _ARID_CEILING_MM:
        return AgroClimaticZone.ARID
    if mean_annual_rainfall_mm < _SEMI_ARID_CEILING_MM:
        return AgroClimaticZone.SEMI_ARID
    if mean_annual_rainfall_mm < _SUB_HUMID_CEILING_MM:
        return AgroClimaticZone.SUB_HUMID
    return AgroClimaticZone.HUMID


def classify_zone_from_normals(rainfall_normal_by_month: dict[int, float]) -> AgroClimaticZone:
    """Zone from a 30-year climatology: the long-term mean annual rainfall.

    Using the climatology rather than the observed years matters: a window
    containing one failed monsoon would otherwise be classified arid and
    validated against arid bounds — a recent drought silently redefining
    normal, the failure Blueprint v2 D6 already fixed for recharge stress.

    Fewer than twelve monthly normals is not extrapolated to a year; the
    annual total is then genuinely unknown.
    """
    if len(rainfall_normal_by_month) < 12:
        return AgroClimaticZone.UNKNOWN
    return classify_zone_by_rainfall(sum(rainfall_normal_by_month.values()))


def ranges_for(zone: AgroClimaticZone) -> ZoneRanges | None:
    """The envelope for a zone, or None when there isn't one.

    `UNKNOWN` has no envelope by design. A caller that receives None must
    skip its zone-dependent checks and record the skip — see
    `ValidationReport.checks_skipped` — rather than substituting the
    widest available range, which would report "validated" for a
    catchment nothing was actually checked against.
    """
    return RANGES_BY_ZONE.get(zone)
