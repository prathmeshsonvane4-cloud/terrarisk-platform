"""Train an age regressor — once the labels can support one.

    python ml/train_age.py ml/features.csv

WHAT THIS REFUSES TO DO
-----------------------
It will not train on fields that were all planted in the same month. A
regressor fed one planting date learns to print that date: it would score
beautifully on the training set, beautifully in cross-validation while
every fold shares the same answer, and be worthless on a field planted in
a different season. The first real batch (21 September 2026) was five
fields all planted in December 2025 — exactly that case, which is why
this gate exists before the model does.

The gates, all of which must pass:
  - 20+ sugarcane fields with a recorded planting date
  - planting dates spanning 4+ distinct months
  - 3+ villages, so the score can be measured out of sample

WHAT IT MEASURES AGAINST
------------------------
The baseline is ml/estimate_age.py's rule: months since green-up plus the
emergence lag. Predicting age from a curve whose rise is already visible
is not obviously a machine-learning problem, so the model has to beat
counting months before it earns a place — the same discipline train.py
applies to detection.

Error is reported in MONTHS (mean absolute error), never as R², which
looks impressive whenever the ages are spread out and says nothing about
whether any single field is dated correctly.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from sklearn.model_selection import LeaveOneGroupOut

from estimate_age import EMERGENCE_LAG_MONTHS

MIN_FIELDS = 20
MIN_DISTINCT_PLANTING_MONTHS = 4
MIN_VILLAGES = 3

NON_FEATURE_COLUMNS = {
    "field_id",
    "label",
    "village",
    "crop",
    "planted",
    "source",
    "cane_type",
    "sown_year",
    "window_start",
    "window_end",
    "greenup_month",
    "age_months",
}


def months_between(planted: str, window_end: str) -> float | None:
    """Whole months from a planting date to the end of the window."""
    try:
        planted_year, planted_month = int(planted[:4]), int(planted[5:7])
        end_year, end_month = int(window_end[:4]), int(window_end[5:7])
    except (ValueError, IndexError):
        return None
    return (end_year - planted_year) * 12 + (end_month - planted_month)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("features", type=Path)
    parser.add_argument("--model-out", type=Path, default=Path("ml/age_model.txt"))
    args = parser.parse_args()

    frame = pd.read_csv(args.features)
    frame = frame[frame["label"] == 1].copy()
    for column in ("planted", "window_end"):
        if column not in frame.columns:
            print(f"{args.features} has no '{column}' column — it predates the age features.")
            print("Delete it and re-run extract_features.py to rebuild with them.")
            return
    frame["age_months"] = [
        months_between(str(p), str(w)) for p, w in zip(frame["planted"], frame["window_end"])
    ]
    frame = frame.dropna(subset=["age_months"])

    planting_months = {str(p)[:7] for p in frame.get("planted", []) if str(p) not in ("", "nan")}
    villages = set(frame["village"])

    print(f"{len(frame)} sugarcane field(s) with a planting date")
    print(f"  planting months: {', '.join(sorted(planting_months)) or 'none'}")
    print(f"  villages: {len(villages)}")

    blocked = []
    if len(frame) < MIN_FIELDS:
        blocked.append(f"{MIN_FIELDS - len(frame)} more dated field(s)")
    if len(planting_months) < MIN_DISTINCT_PLANTING_MONTHS:
        blocked.append(
            f"{MIN_DISTINCT_PLANTING_MONTHS - len(planting_months)} more distinct planting month(s) — "
            "cane here is planted November to March, so collect across that whole span, "
            "and include ratoon fields cut at different times"
        )
    if len(villages) < MIN_VILLAGES:
        blocked.append(f"{MIN_VILLAGES - len(villages)} more village(s)")

    if blocked:
        print("\nNOT TRAINING. Still needed: " + "; ".join(blocked))
        print("\nA regressor trained on fields that share one planting date learns to print")
        print("that date. It would look accurate in every fold and be wrong on any field")
        print("planted in another season. Use ml/estimate_age.py meanwhile — it counts the")
        print("months since green-up and says plainly where it is only a lower bound.")
        return

    # ---------------------------------------------------------------
    # Baseline: count the months, exactly as estimate_age.py does.
    # ---------------------------------------------------------------
    truth = frame["age_months"].to_numpy(dtype=float)
    baseline = frame["months_since_greenup"].to_numpy(dtype=float) + EMERGENCE_LAG_MONTHS
    usable = ~np.isnan(baseline)
    baseline_error = float(np.mean(np.abs(baseline[usable] - truth[usable])))
    print(f"\nBASELINE months since green-up + {EMERGENCE_LAG_MONTHS}: "
          f"mean absolute error {baseline_error:.2f} months on {usable.sum()} field(s)")

    features = [c for c in frame.columns if c not in NON_FEATURE_COLUMNS and not c.startswith(("ndvi_2", "vv_2", "vh_2"))]
    X = frame[features].to_numpy(dtype=float)
    groups = frame["village"].to_numpy()

    predictions = np.full(len(frame), np.nan)
    for train_index, test_index in LeaveOneGroupOut().split(X, truth, groups=groups):
        model = LGBMRegressor(n_estimators=400, learning_rate=0.05, num_leaves=8, min_child_samples=5, verbose=-1)
        model.fit(X[train_index], truth[train_index])
        predictions[test_index] = model.predict(X[test_index])

    model_error = float(np.mean(np.abs(predictions - truth)))
    within_one = float(np.mean(np.abs(predictions - truth) <= 1))
    within_two = float(np.mean(np.abs(predictions - truth) <= 2))

    print(f"MODEL    leave-one-village-out: mean absolute error {model_error:.2f} months")
    print(f"         {within_one:.0%} of fields within 1 month, {within_two:.0%} within 2")

    print(f"\n{'=' * 58}")
    if model_error >= baseline_error - 0.25:
        print("VERDICT: the model does not beat counting months since green-up.")
        print("         Ship the rule (ml/estimate_age.py); it is explainable to a bank.")
    else:
        print(f"VERDICT: the model earns its place ({baseline_error - model_error:.2f} months better).")
    print("=" * 58)

    final = LGBMRegressor(n_estimators=400, learning_rate=0.05, num_leaves=8, min_child_samples=5, verbose=-1)
    final.fit(X, truth)
    args.model_out.parent.mkdir(parents=True, exist_ok=True)
    final.booster_.save_model(str(args.model_out))
    print(f"\nmodel written to {args.model_out}")

    importance = sorted(zip(features, final.feature_importances_), key=lambda pair: -pair[1])
    print("\ntop features:")
    for name, value in importance[:8]:
        print(f"  {name:24} {value}")


if __name__ == "__main__":
    main()
