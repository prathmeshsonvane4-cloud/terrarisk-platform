# Sugarcane detector — daily workflow

Detecting sugarcane from how long a field stays green (12–18 months, against
about 4 for an annual crop), so a lender or a programme can see what is
actually growing on a plot without visiting it.

Everything here runs from the repository root, in the training environment:

```bash
.venv-train/Scripts/python.exe ml/<script>.py ...     # Windows
```

## The daily loop

```bash
# 1. Put the day's fields in a file (copy ml/incoming/TEMPLATE.txt)
python ml/add_labels_bulk.py ml/incoming/2026-09-21.txt --dry-run   # check first
python ml/add_labels_bulk.py ml/incoming/2026-09-21.txt             # then write

# 2. See what the set has and what it still needs
python ml/dataset_status.py

# 3. Pull satellite history for the new fields (skips ones already done)
python ml/extract_features.py ml/labels.geojson ml/features.csv

# 4. Train and validate — only once dataset_status says a verdict is possible
python ml/train.py ml/features.csv
```

Step 3 takes roughly 20–30 seconds per field, and is resumable: a failure at
field 250 does not cost the first 249.

## What to collect

| | Target | Why |
|---|---|---|
| Sugarcane fields | 30+ | Fewer cannot support any claim |
| Non-sugarcane fields | 30+ | A classifier cannot learn "cane" without "not cane" |
| Villages | 4+ | The model is scored on villages it never trained on |
| Plant cane | 3+ | New cane sits at bare-soil NDVI for months |
| Ratoon cane | 3+ | Regrown cane is green from the start — a different shape |
| Tricky non-cane | as many as possible | Banana, orchards and fodder stay green too; they are the real test |

No village should hold more than about 40% of the fields, or the folds are
really one fold and the score measures that village.

**Field size.** One point draws a 50 m square, and the extractor shaves 10 m
off each side before reading pixels, leaving ~9 clean Sentinel-2 pixels. For a
field smaller than about 0.6 acre, or a narrow strip, give 3+ corners instead.

**The one rule that cannot bend:** a label records what is known on the ground
— seen, owner-stated or mill-recorded. Never label from NDVI, from a basemap
guess dressed up as fact, or from what the model predicts. The labels are what
the model is measured against; deriving them from the same imagery the model
learns from measures nothing at all.

## What each script does

| Script | Purpose |
|---|---|
| `add_labels_bulk.py` | Reads the day's text file. Fixes swapped lat/lon, rejects coordinates outside Latur, refuses sugarcane without plant/ratoon, skips pins within 40 m of a field already labelled, assigns ids |
| `add_label.py` | One field at a time, same rules |
| `dataset_status.py` | Counts, and the gates: can the pipeline run, can training report a verdict, can a result be shown outside the project |
| `extract_features.py` | Sentinel-2 NDVI/NDMI and Sentinel-1 radar per month per field, to `features.csv` |
| `features.py` | The phenology features themselves — pure functions, no network, unit-tested |
| `train.py` | Threshold baseline first, then LightGBM scored leave-one-village-out, then a verdict that is withheld below 30 fields |
| `estimate_age.py` | Approximate crop age in months, from the curve — a rule, usable today, printed as a range |
| `train_age.py` | The learned age regressor, refused until planting dates span 4+ months |
| `compare_fields.py` | Every field's monthly NDVI side by side, the harvest and regrowth month each curve shows, agreement with the farmer's dates, and how alike the curves are |
| `timeseries.py` | A daily NDVI series for any point or field, fused from Sentinel-2, Landsat 8/9 and Sentinel-1, with every day labelled observed / interpolated / radar-estimated / harvest window / no data |
| `timeseries_plot.py` | The chart for one field's daily series |
| `farm_context.py` | One row per day per farm: canopy, rainfall, weather, FAO-56 ET0, soil moisture, heat, haze, surface water |
| `farm_context_plot.py` | The farm's year on one shared time axis |
| `plot_report.py` | NDVI curves per field, for eyeballing labels |

## Crop age

Age is months since the canopy left bare soil, plus the weeks the crop
spent below detection before that. It is reported as a **range**, because
that lag varies: of three December 2025 plantings in Shera, one crossed
NDVI 0.30 in February and two not until April.

```bash
python ml/estimate_age.py ml/features.csv
```

What the imagery can and cannot say:

- **NDVI alone cannot date a closed canopy.** It saturates near 0.8, so a
  five-month field and a ten-month field look the same. NDRE (red edge)
  and EVI keep responding past that point, and radar (VV, VH, RVI) tracks
  canopy structure through monsoon cloud — all three are extracted.
- **Finer resolution is not available for free.** Sentinel-2 is 10 m for
  NDVI and 20 m for the red-edge bands; on a 0.2 ha plot that is a handful
  of pixels. Planet's 3 m imagery is paid.
- **A green-up in April–June is ambiguous** — a late-emerging winter
  planting, or ratoon regrowth after a harvest, look identical. The output
  says so rather than choosing.
- **Training an age model needs variation in age.** Fields all planted in
  the same month teach a regressor to print that month. `train_age.py`
  refuses until there are 20+ dated fields spanning 4+ planting months
  across 3+ villages, and it must beat simply counting months to ship.

## A daily series for any farm

```bash
python ml/timeseries.py --point 18.5527,76.4970 --plot          # any coordinate
python ml/timeseries.py --field shera-02 --plot                 # a labelled field
python ml/timeseries.py --all-fields                            # every field + ml/output/summary.csv
```

What the free satellites actually give over the Shera block, measured
23 Sep 2026 for the previous twelve months:

| Sensor | Pixel | Bands used | Revisit measured here | Notes |
|---|---|---|---|---|
| Sentinel-2A/2B/2C (MSI) | 10 m (20 m red edge) | B2, B4, B5, B8, B8A | every 4.1 days | 2A on an extension campaign to end-2026; 12-bit |
| Landsat 8 / 9 (OLI) | 30 m | B4, B5 | ~every 9 days combined | Mixed pixels on small plots — calibrated per field |
| Sentinel-1C/1D (C-band SAR) | 10 m | VV, VH, incidence angle | every ~13 days | One descending track over Shera; since July 2026 only 1D images it |
| MODIS Terra | 250 m | — | daily | Not used: one pixel is 6 ha, bigger than the farms |
| NISAR (L-band SAR) | 3–10 m | — | 12 days | Public since June 2026 via NASA ASF, not in Earth Engine yet |

**"Daily" means observed plus honestly-labelled interpolation.** On shera-02
the pipeline had a clear view on 79 of 365 days (median gap 4 days,
longest 28 in July), interpolated 74% of days, and could say nothing on 3%.
Every row carries `days_to_view`, so a value inferred from a view ten days
old never passes for today's.

**Radar is not used to fill gaps on these fields**, and the pipeline
refuses it on purpose: on shera-02 a VH/VV model predicted held-out NDVI
with R² of about 0. C-band backscatter on a 0.1–0.3 ha plot is dominated by
speckle and soil moisture, and saturates over a tall cane canopy. It still
shows the harvest (VH fell to −21 dB in the cut week), so it remains
useful as corroboration, not as a substitute for optical NDVI.

## Everything around the farm

```bash
python ml/farm_context.py --field shera-13 --plot
python ml/farm_context.py --point 18.5527,76.4970 --plot
```

One row per day: fused NDVI, NIRv and NDMI; rainfall (GPM IMERG, ~1 day
behind; CHIRPS v3, ~3-4 weeks behind); ERA5-Land max/min temperature,
dewpoint, solar radiation and pressure, with wind averaged from hourly
components; **FAO-56 Penman-Monteith reference ET0** computed from them
(checked against FAO-56 Examples 8 and 18); rainfall minus ET0, daily and
over 30 days; SMAP L4 surface and root-zone soil moisture; MODIS land
surface temperature; MAIAC aerosol; Dynamic World surface water on the
field and within 1 km. A JSON file carries the static setting (elevation,
clay and sand, historical surface water) and each source's freshness.

Why NIRv and not raw NIR: NIR reflectance tracks canopy structure, but on
its own it also rises with bright soil and falls with haze. NDVI x NIR
keeps NIR's sensitivity and cancels most of the soil background.

What is not there, and why:

- **Groundwater.** No satellite measures it at farm scale (GRACE-FO is
  hundreds of km and months late). It needs CGWB / GSDA well readings, and
  the platform's CGWB table is empty.
- **Crop water use.** ET0 is the demand of reference grass. Cane water use
  needs a crop-coefficient curve tied to the crop's stage — a model not
  yet built, so nothing is labelled as crop water use.
- **Field-scale weather.** Rain, temperature and soil moisture grids are
  1-11 km: every farm in a village shares one value.

## Gates before quoting a number

1. **Pipeline runs** — one labelled field.
2. **A verdict is possible** — 30+ fields across 2+ villages. Below this
   `train.py` prints its numbers as a pipeline check and withholds the verdict,
   because a score from five fields is the class balance with a decimal point.
3. **A result can leave this project** — the targets in the table above. Quote
   it with its confusion matrix and the villages it was tested on, never as a
   bare accuracy figure.

A run on 5 fields, done as a rehearsal on 21 Sep 2026, reported
`NO FEATURE WAS USED. The trees never split, so nothing was learned` — which
is the correct answer at that size, and the reason these gates exist.
