"""One farm's year on a shared time axis: canopy, water demand and supply,
soil moisture, temperature.

Small multiples, one quantity per panel, never two y-scales on one axis.
Rainfall and ET0 share a panel because they share a unit (mm/day) and are
meant to be read against each other; everything else gets its own.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

# Reference palette, light mode (dataviz skill, references/palette.md);
# categorical slots in their fixed order.
SURFACE = "#fcfcfb"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
GRID = "#e4e3df"
SLOT_1 = "#2a78d6"   # blue
SLOT_2 = "#eb6834"   # orange
SLOT_3 = "#1baf7a"   # aqua
HARVEST = "#e34948"


def _series(rows, key):
    xs, ys = [], []
    for row in rows:
        if row.get(key) is not None:
            xs.append(date.fromisoformat(row["date"]))
            ys.append(row[key])
    return xs, ys


def _runs(rows, key):
    """Consecutive days with a value, so lines break across real gaps."""
    run_x, run_y = [], []
    for row in rows:
        if row.get(key) is None:
            if run_x:
                yield run_x, run_y
            run_x, run_y = [], []
            continue
        run_x.append(date.fromisoformat(row["date"]))
        run_y.append(row[key])
    if run_x:
        yield run_x, run_y


def plot_context(name: str, rows: list[dict], ndvi_series, out_dir: Path) -> Path:
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Segoe UI", "Helvetica", "Arial", "DejaVu Sans"],
        "font.size": 9.5, "text.color": TEXT_PRIMARY, "axes.labelcolor": TEXT_SECONDARY,
        "xtick.color": TEXT_SECONDARY, "ytick.color": TEXT_SECONDARY,
    })
    fig, axes = plt.subplots(5, 1, figsize=(12.5, 11.5), sharex=True, facecolor=SURFACE,
                             gridspec_kw={"height_ratios": [1.3, 1, 1.2, 1, 1]})
    fig.subplots_adjust(left=0.08, right=0.98, top=0.90, bottom=0.07, hspace=0.32)
    canopy, nirv, water, soil, heat = axes

    for ax in axes:
        ax.set_facecolor(SURFACE)
        ax.grid(axis="y", color=GRID, lw=0.7)
        ax.set_axisbelow(True)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        ax.tick_params(length=0)
        for standing, cut in ndvi_series.breaks:
            ax.axvspan(standing, cut, color=HARVEST, alpha=0.12, lw=0, zorder=0)

    for xs, ys in _runs(rows, "ndvi"):
        canopy.plot(xs, ys, color=SLOT_1, lw=1.8)
    canopy.set_ylabel("NDVI")
    canopy.set_ylim(0, 0.95)
    canopy.set_title("Canopy greenness — NDVI, fused daily from Sentinel-2 and Landsat", loc="left", fontsize=10.5,
                     color=TEXT_PRIMARY, fontweight="semibold")
    for standing, cut in ndvi_series.breaks:
        canopy.text(standing + (cut - standing) / 2, 0.9, "harvest", ha="center", va="top", fontsize=8.5,
                    color=TEXT_SECONDARY)

    for xs, ys in _runs(rows, "nirv"):
        nirv.plot(xs, ys, color=SLOT_1, lw=1.8)
    nirv.set_ylabel("NIRv")
    nirv.set_title("NIRv = NDVI × NIR — canopy structure, saturates later than NDVI", loc="left",
                   fontsize=10.5, color=TEXT_PRIMARY, fontweight="semibold")

    rx, ry = _series(rows, "rain_imerg_mm")
    water.bar(rx, ry, width=1.0, color=SLOT_1, lw=0, label="Rainfall (GPM IMERG, 11 km)")
    for xs, ys in _runs(rows, "et0_mm"):
        water.plot(xs, ys, color=SLOT_2, lw=1.6)
    water.set_ylabel("mm / day")
    # Cap the axis at 60 mm so one cloudburst does not flatten every other day.
    water.set_ylim(0, max(10, min(max(ry, default=10), 60)) * 1.05)
    water.set_title("Water supply and demand — rainfall vs FAO-56 reference evapotranspiration (ERA5-Land)",
                    loc="left", fontsize=10.5, color=TEXT_PRIMARY, fontweight="semibold")
    water.legend(handles=[Patch(facecolor=SLOT_1, label="Rainfall (IMERG)"),
                          Line2D([0], [0], color=SLOT_2, lw=1.6, label="Reference ET0")],
                 loc="lower right", bbox_to_anchor=(1.0, 1.0), frameon=False, fontsize=8.8,
                labelcolor=TEXT_SECONDARY, ncol=2, borderaxespad=0.2)

    for key, color in (("smap_sm_surface", SLOT_1), ("smap_sm_rootzone", SLOT_3)):
        for xs, ys in _runs(rows, key):
            soil.plot(xs, ys, color=color, lw=1.6)
    soil.set_ylabel("m³ / m³")
    soil.set_title("Soil moisture — SMAP L4 (9 km, regional)", loc="left", fontsize=10.5, color=TEXT_PRIMARY,
                   fontweight="semibold")
    soil.legend(handles=[Line2D([0], [0], color=SLOT_1, lw=1.6, label="Surface 0–5 cm"),
                         Line2D([0], [0], color=SLOT_3, lw=1.6, label="Root zone")],
                loc="lower right", bbox_to_anchor=(1.0, 1.0), frameon=False, fontsize=8.8,
                labelcolor=TEXT_SECONDARY, ncol=2, borderaxespad=0.2)

    for key, color in (("tmax_c", SLOT_2), ("tmin_c", SLOT_1)):
        for xs, ys in _runs(rows, key):
            heat.plot(xs, ys, color=color, lw=1.4)
    heat.set_ylabel("°C")
    heat.set_title("Air temperature — ERA5-Land daily max and min (11 km)", loc="left", fontsize=10.5,
                   color=TEXT_PRIMARY, fontweight="semibold")
    heat.legend(handles=[Line2D([0], [0], color=SLOT_2, lw=1.4, label="Max"),
                         Line2D([0], [0], color=SLOT_1, lw=1.4, label="Min")],
                loc="lower right", bbox_to_anchor=(1.0, 1.0), frameon=False, fontsize=8.8,
                labelcolor=TEXT_SECONDARY, ncol=2, borderaxespad=0.2)

    heat.xaxis.set_major_locator(mdates.MonthLocator())
    heat.xaxis.set_major_formatter(mdates.DateFormatter("%b\n%Y"))
    first, last = date.fromisoformat(rows[0]["date"]), date.fromisoformat(rows[-1]["date"])
    heat.set_xlim(first, last)

    rain = sum(r["rain_imerg_mm"] for r in rows if r["rain_imerg_mm"] is not None)
    et0 = sum(r["et0_mm"] for r in rows if r["et0_mm"] is not None)
    fig.text(0.08, 0.955, f"{name} — the farm's year, from every free source", fontsize=15, fontweight="semibold")
    fig.text(0.08, 0.93, f"{first:%d %b %Y} to {last:%d %b %Y}: rainfall {rain:.0f} mm, reference ET0 {et0:.0f} mm. "
             "Red strips: harvest windows. Weather and soil grids are 9–11 km — one value for the whole village.",
             fontsize=9.5, color=TEXT_SECONDARY)
    fig.text(0.08, 0.02, "Groundwater is not shown: no satellite measures it at farm scale; it needs CGWB/GSDA well "
             "readings, not yet in the platform.", fontsize=8.5, color=TEXT_SECONDARY)

    path = out_dir / f"{name}_context.png"
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)
    return path
