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
| `plot_report.py` | NDVI curves per field, for eyeballing labels |

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
