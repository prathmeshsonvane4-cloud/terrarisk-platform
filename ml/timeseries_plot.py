"""Chart for one field's fused daily series: what was seen, what was
inferred, and where nothing could be said.

Two panels on a shared time axis rather than one chart with two y-scales:
NDVI and radar backscatter are different quantities, and a second axis
would let the eye read a relationship the data does not claim.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

# Reference palette, light mode (dataviz skill, references/palette.md).
SURFACE = "#fcfcfb"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
GRID = "#e4e3df"
S2_COLOR = "#2a78d6"        # categorical slot 1
LANDSAT_COLOR = "#eb6834"   # categorical slot 2
RADAR_COLOR = "#1baf7a"     # categorical slot 3
FUSED = "#52514e"
NO_DATA = "#f0efe9"


def _runs(days, values, flags, wanted):
    """Consecutive stretches of days whose flag is in `wanted`."""
    run_x, run_y = [], []
    for day, value, flag in zip(days, values, flags):
        if flag in wanted and value is not None:
            run_x.append(day)
            run_y.append(value)
        elif run_x:
            yield run_x, run_y
            run_x, run_y = [], []
    if run_x:
        yield run_x, run_y


def plot_series(name, series, observations, out_dir: Path) -> Path:
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Segoe UI", "Helvetica", "Arial", "DejaVu Sans"],
        "font.size": 10, "text.color": TEXT_PRIMARY, "axes.labelcolor": TEXT_SECONDARY,
        "xtick.color": TEXT_SECONDARY, "ytick.color": TEXT_SECONDARY,
    })
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(12.5, 7.2), sharex=True, facecolor=SURFACE,
                                      gridspec_kw={"height_ratios": [2.3, 1]})
    fig.subplots_adjust(left=0.07, right=0.98, top=0.83, bottom=0.10, hspace=0.18)

    for ax in (top, bottom):
        ax.set_facecolor(SURFACE)
        ax.grid(axis="y", color=GRID, lw=0.7)
        ax.set_axisbelow(True)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(GRID)
        ax.tick_params(length=0)

    # Where nothing could be said, shade it — an empty stretch, not a line.
    for run_x, _ in _runs(series.days, [0] * len(series.days), series.flag, {"no_data"}):
        for ax in (top, bottom):
            ax.axvspan(run_x[0], run_x[-1] + timedelta(days=1), color=NO_DATA, lw=0, zorder=0)

    for run_x, run_y in _runs(series.days, series.ndvi, series.flag, {"observed", "interpolated"}):
        top.plot(run_x, run_y, color=FUSED, lw=1.6, zorder=2, solid_capstyle="round")
    for run_x, run_y in _runs(series.days, series.ndvi, series.flag, {"radar_estimated"}):
        top.plot(run_x, run_y, color=RADAR_COLOR, lw=1.6, ls=(0, (3, 2)), zorder=2)

    outliers = set(series.outliers)
    s2 = [o for o in observations if o.sensor == "S2" and o.ndvi is not None]
    landsat = [o for o in observations if o.sensor in ("L8", "L9") and o.ndvi is not None]
    kept_s2 = [o for o in s2 if o.day not in outliers]
    kept_landsat = [o for o in landsat if o.day not in outliers]
    top.plot([o.day for o in kept_s2], [o.ndvi for o in kept_s2], "o", color=S2_COLOR, ms=5.5, mec=SURFACE,
             mew=1.2, zorder=4)
    top.plot([o.day for o in kept_landsat], [series.calibration.apply(o.ndvi) for o in kept_landsat], "s",
             color=LANDSAT_COLOR, ms=5.5, mec=SURFACE, mew=1.2, zorder=4)
    # Outlier passes stay visible — hollow — so nothing is hidden from the reader.
    odd = [(o.day, o.ndvi if o.sensor == "S2" else series.calibration.apply(o.ndvi))
           for o in s2 + landsat if o.day in outliers]
    if odd:
        top.plot([d for d, _ in odd], [v for _, v in odd], "o", mfc="none", mec=TEXT_SECONDARY, ms=6, mew=1.2,
                 zorder=4)

    # Each harvest: the stretch between the last view of the standing crop
    # and the first view of the cut, where the day of the cut is unknown.
    for standing, cut in series.breaks:
        for ax in (top, bottom):
            ax.axvspan(standing, cut, color="#e34948", alpha=0.10, lw=0, zorder=0)
        top.text(standing + (cut - standing) / 2, 0.92, "harvest", ha="center", va="top", fontsize=8.5,
                 color=TEXT_SECONDARY)
    top.set_ylim(0, 0.95)
    top.set_ylabel("NDVI")

    radar = sorted((o for o in observations if o.sensor == "S1"), key=lambda o: o.day)
    if radar:
        bottom.plot([o.day for o in radar], [o.vh_db for o in radar], color=RADAR_COLOR, lw=1.2, zorder=2)
        bottom.plot([o.day for o in radar], [o.vh_db for o in radar], "o", color=RADAR_COLOR, ms=5.5,
                    mec=SURFACE, mew=1.2, zorder=3)
    bottom.set_ylabel("VH γ⁰ (dB)")
    bottom.xaxis.set_major_locator(mdates.MonthLocator())
    bottom.xaxis.set_major_formatter(mdates.DateFormatter("%b\n%Y"))
    bottom.set_xlim(series.days[0], series.days[-1])

    counts = {f: series.flag.count(f)
              for f in ("observed", "interpolated", "radar_estimated", "harvest_between_views", "no_data")}
    total = len(series.days)
    fig.text(0.07, 0.955, f"{name} — daily NDVI from every free sensor", fontsize=15, fontweight="semibold")
    fig.text(0.07, 0.918,
             f"{counts['observed']} days seen clearly ({counts['observed'] / total:.0%}), "
             f"{counts['interpolated']} interpolated ({counts['interpolated'] / total:.0%}, "
             f"±{series.interpolation_rmse:.2f} NDVI, ±{series.interpolation_rmse_all:.2f} counting odd passes), "
             f"{counts['radar_estimated']} from radar, "
             f"{counts['harvest_between_views']} inside a harvest window, "
             f"{counts['no_data']} with no recent view ({counts['no_data'] / total:.0%}).",
             fontsize=10, color=TEXT_SECONDARY)
    legend = [
        Line2D([0], [0], color=S2_COLOR, marker="o", ls="", ms=5.5, mec=SURFACE, mew=1.2, label="Sentinel-2"),
        Line2D([0], [0], color=LANDSAT_COLOR, marker="s", ls="", ms=5.5, mec=SURFACE, mew=1.2,
               label="Landsat 8/9 (calibrated)"),
        Line2D([0], [0], color=TEXT_SECONDARY, marker="o", ls="", mfc="none", ms=6, mew=1.2,
               label="Outlier pass (down-weighted)"),
        Line2D([0], [0], color=FUSED, lw=1.6, label="Daily series"),
        Line2D([0], [0], color=RADAR_COLOR, lw=1.6, ls=(0, (3, 2)), label="From radar"),
        Patch(facecolor="#e34948", alpha=0.10, label="Harvest window"),
        Patch(facecolor=NO_DATA, label="No view within 10 days"),
    ]
    fig.legend(handles=legend, loc="upper left", bbox_to_anchor=(0.065, 0.905), ncol=7, frameon=False,
               fontsize=8.8, labelcolor=TEXT_SECONDARY, handlelength=1.6, columnspacing=1.1)
    fig.text(0.07, 0.02, "Sentinel-2 L2A with Cloud Score+ (cs_cdf ≥ 0.60); Landsat 8/9 C2 L2 QA mask; "
             "Sentinel-1 GRD IW, γ⁰ in linear power. A view counts only if ≥ 80% of the field is clear.",
             fontsize=8.5, color=TEXT_SECONDARY)

    path = out_dir / f"{name}_daily.png"
    fig.savefig(path, dpi=160, facecolor=SURFACE)
    plt.close(fig)
    return path
