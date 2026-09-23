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
