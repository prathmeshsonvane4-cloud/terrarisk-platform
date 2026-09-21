"""Approximate age of the standing crop, in months, from the NDVI curve.

    python ml/estimate_age.py ml/features.csv

WHY THIS IS A RULE AND NOT A MODEL (YET)
----------------------------------------
Age is not hidden in the imagery the way a crop type is. It is the time
since the canopy left bare soil, and that date is visible directly in the
monthly series. A rule that counts the months is therefore the thing a
learned model has to beat, exactly as the green-run threshold is the
baseline for detection (ml/train.py). ml/train_age.py will train that
model once there are fields planted across several different months —
until then a regressor would only learn the one planting date in the set.

WHAT THE NUMBER MEANS, AND WHAT IT DOES NOT
-------------------------------------------
It is months since GREEN-UP, plus the time the crop spent below the
detection threshold before that. Cane planted in the cool months emerges
slowly and unevenly: of three December 2025 plantings in Shera, one
crossed NDVI 0.30 in February and two not until April. So the answer is
printed as a RANGE, never as a single month.

Honesty rules, each stated per field in the output:
  - If the green-up was not seen (the field was already green when the
    window opened) the answer is a LOWER BOUND, never an age.
  - A green-up between April and June cannot be told apart from ratoon
    regrowth by the curve alone, and the output says so instead of
    choosing. July-October is outside anything a local planting explains.
  - Monthly observations mean the answer is +/- 1 month at best, and
    worse through a monsoon gap. No decimal places are printed.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from features import in_emergence_window  # noqa: E402

# Months between putting a sett in the ground and the canopy crossing
# NDVI 0.30. Two observations, both from Shera, both December plantings,
# and they disagree: one crossed in February (2 months), two crossed in
# April (4 months). A winter planting sits below detection until the heat
# arrives, and how long that takes clearly varies.
#
# So the lag is a RANGE and the answer is printed as a range. Collapsing
# it to one number would turn a two-month uncertainty into false
# precision in front of a lender. Narrowing it needs fields with known
# planting dates across the whole November-March span — see train_age.py.
EMERGENCE_LAG_MONTHS = 2
EMERGENCE_LAG_RANGE = (2, 4)

# Sugarcane runs 12-18 months. Past that, either the field was harvested
# and this is ratoon, or the green run is not cane at all.
PLAUSIBLE_MAX_MONTHS = 18


def describe(row: dict) -> str:
    months = row.get("months_since_greenup")
    if months in (None, ""):
        return "no green period found — nothing to date"

    months = int(float(months))
    lower_bound = str(row.get("age_is_lower_bound", "")) in ("1", "1.0", "True")
    in_window = str(row.get("greenup_in_planting_window", ""))
    greenup = row.get("greenup_month", "")

    if lower_bound:
        return (
            f"at least {months} months since green-up (green-up not seen — the field was "
            f"already green when the record starts, so this is a floor, not an age)"
        )

    low, high = (months + lag for lag in EMERGENCE_LAG_RANGE)
    parts = [f"{low}-{high} months old ({months} months of canopy from {greenup}, plus emergence)"]

    greenup_month_number = int(greenup[5:7]) if greenup else 0
    if in_window == "1":
        parts.append("green-up is in the November-March planting window")
    elif in_emergence_window(greenup_month_number):
        # The case the first real fields showed: December plantings whose
        # canopy only appeared in April. Indistinguishable from a ratoon
        # cut in March, so both are stated.
        parts.append(
            "green-up is after the planting window but within the months a winter planting "
            "takes to emerge — either a November-March planting that emerged late, or ratoon "
            "regrowth after a harvest. The curve alone cannot separate them"
        )
    else:
        parts.append(
            "green-up is in July-October, when cane is not planted here — most likely ratoon "
            "regrowth, so read it as months since the last harvest, or the field is not cane"
        )

    if high > PLAUSIBLE_MAX_MONTHS:
        parts.append(
            f"over {PLAUSIBLE_MAX_MONTHS} months exceeds a cane cycle — either it was harvested "
            "and regrew, or the green run is not cane"
        )
    return "; ".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("features", type=Path, help="features.csv from extract_features.py")
    parser.add_argument("--cane-only", action="store_true", help="Only fields labelled sugarcane")
    args = parser.parse_args()

    with args.features.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if args.cane_only:
        rows = [row for row in rows if row.get("label") == "1"]

    if not rows:
        print("no fields to report on")
        return

    window = rows[0].get("window_start", ""), rows[0].get("window_end", "")
    print(f"Age at the end of the observation window ({window[0]} to {window[1]})\n")
    for row in rows:
        print(f"  {row['field_id']:16} {row.get('village', ''):14} {describe(row)}")

    dated = [r for r in rows if str(r.get("greenup_observed", "")) in ("1", "1.0")]
    print(f"\n{len(dated)} of {len(rows)} field(s) had their green-up inside the window and can be dated.")
    print("Every figure is +/- 1 month at best: observations are monthly, and cloud can")
    print("hide the month a canopy actually closed.")

    known = [r for r in rows if r.get("planted")]
    if known:
        print("\nAgainst the planting dates you recorded:")
        for row in known:
            print(f"  {row['field_id']:16} recorded {row['planted']:12} vs {describe(row)}")
        print("This comparison is the only real check on the rule. Until several fields")
        print("with known, DIFFERENT planting dates exist, it cannot be turned into an")
        print("error figure — see ml/train_age.py.")


if __name__ == "__main__":
    main()
