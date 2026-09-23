"""Train and honestly validate the sugarcane classifier.

    python ml/train.py features.csv

WHAT THIS DELIBERATELY DOES
---------------------------
Reports a BASELINE FIRST: a single threshold on how many months the
field stayed continuously green. Sugarcane runs 12-18 months, an
annual crop about four, so that one number already separates them
fairly well. If LightGBM cannot beat it, the honest conclusion is
that we built a threshold with extra steps — and that conclusion
should be impossible to avoid seeing.

Validates by LEAVE-ONE-VILLAGE-OUT, never a random split. Fields in one
village share soil, rainfall, management, and often a farmer. A random
split puts near-identical fields on both sides of the line and reports
skill that is really memorisation. Ploton et al. (2020) showed a random
forest that looked strong on a random split and had NO predictive skill
under spatial validation; this is the same trap.

Reports precision, recall and a confusion matrix, never bare accuracy.
Sugarcane is a minority class, so "always predict no" scores well on
accuracy while being useless.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support, roc_auc_score
from sklearn.model_selection import LeaveOneGroupOut

# Below this many fields, leave-one-village-out folds are too small to
# fit anything and the resulting score is noise wearing a decimal point.
# A green-light run on three fields scored a perfect F1 while the model
# made no splits at all — the number came from luck and a fallback, not
# from learning. The verdict is withheld rather than printed with a
# caveat, because a caveat under a headline number gets skimmed past.
MIN_FIELDS_FOR_VERDICT = 30

NON_FEATURE_COLUMNS = {
    "field_id",
    "label",
    "village",
    "crop",
    "planted",
    "source",
    "cane_type",
    "sown_year",
    # Text and date columns added with the age features. They describe a
    # field's calendar, not its curve, and are not numbers.
    "cut_date",
    "window_start",
    "window_end",
    "greenup_month",
}


def _feature_columns(frame: pd.DataFrame) -> list[str]:
    """Summary features only — not the raw per-month columns.

    The monthly columns are kept in the CSV for inspection and plotting,
    but feeding them in directly ties the model to specific calendar
    months of one particular season. The summary features (min,
    amplitude, longest green run) describe the SHAPE of the curve, which
    is what actually generalises to another year.
    """
    return [
        column
        for column in frame.columns
        if column not in NON_FEATURE_COLUMNS
        and not column.startswith(("ndvi_2", "vv_2", "vh_2", "rvi_2"))
    ]


def _report(name: str, y_true: np.ndarray, y_pred: np.ndarray, y_score: np.ndarray | None = None) -> dict:
    precision, recall, f1, _ = precision_recall_fscore_support(
        y_true, y_pred, average="binary", zero_division=0
    )
    matrix = confusion_matrix(y_true, y_pred, labels=[0, 1])
    (true_neg, false_pos), (false_neg, true_pos) = matrix

    print(f"\n--- {name} ---")
    print(f"  precision {precision:.3f}   recall {recall:.3f}   F1 {f1:.3f}")
    if y_score is not None and len(set(y_true)) > 1:
        print(f"  ROC AUC   {roc_auc_score(y_true, y_score):.3f}")
    print("                 predicted")
    print("               other  sugarcane")
    print(f"  actual other  {true_neg:5d} {false_pos:9d}")
    print(f"     sugarcane  {false_neg:5d} {true_pos:9d}")
    if false_pos:
        print(f"  {false_pos} field(s) wrongly called sugarcane")
    if false_neg:
        print(f"  {false_neg} sugarcane field(s) missed")
    return {"precision": precision, "recall": recall, "f1": f1}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("features", type=Path)
    parser.add_argument(
        "--baseline-run",
        type=int,
        default=6,
        help="Baseline: months of continuous green above which a field is called sugarcane",
    )
    parser.add_argument("--model-out", type=Path, default=Path("ml/sugarcane_model.txt"))
    args = parser.parse_args()

    frame = pd.read_csv(args.features)
    frame = frame.dropna(subset=["longest_green_run"])
    y = frame["label"].to_numpy()
    villages = frame["village"].to_numpy()

    print(f"{len(frame)} fields | {int(y.sum())} sugarcane, {int((1 - y).sum())} other")
    print(f"{len(set(villages))} villages")
    print(f"class balance: {y.mean():.1%} sugarcane")

    if len(set(villages)) < 2:
        print(
            "\nWARNING: fewer than 2 villages. Leave-one-village-out cannot run, and any\n"
            "         score below would be measured on fields the model has effectively\n"
            "         already seen. Label fields across several villages before believing\n"
            "         any number this produces."
        )

    # ---------------------------------------------------------------
    # Baseline. Must be beaten for the model to have earned its place.
    # ---------------------------------------------------------------
    # Duration, not minimum. A real plot settled this: newly planted
    # cane sits at bare-soil NDVI for months while it is below detection,
    # so a minimum-NDVI rule misses every new planting. How long the
    # field stays green is what actually separates cane from an annual
    # crop. See ml/features.py.
    baseline_pred = (frame["longest_green_run"] >= args.baseline_run).astype(int).to_numpy()
    baseline = _report(
        f"BASELINE: longest_green_run >= {args.baseline_run} months",
        y,
        baseline_pred,
        frame["longest_green_run"].to_numpy(),
    )

    # ---------------------------------------------------------------
    # Model, scored ONLY on villages it never trained on.
    # ---------------------------------------------------------------
    features = _feature_columns(frame)
    X = frame[features].to_numpy(dtype=float)
    print(f"\n{len(features)} features: {', '.join(features)}")

    if len(set(villages)) < 2:
        return

    predictions = np.zeros(len(y), dtype=int)
    scores = np.zeros(len(y), dtype=float)
    for train_index, test_index in LeaveOneGroupOut().split(X, y, groups=villages):
        if len(set(y[train_index])) < 2:
            # A fold whose training half is single-class teaches nothing.
            predictions[test_index] = 0
            continue
        model = LGBMClassifier(
            n_estimators=300, learning_rate=0.05, num_leaves=8, min_child_samples=5, verbose=-1
        )
        model.fit(X[train_index], y[train_index])
        scores[test_index] = model.predict_proba(X[test_index])[:, 1]
        predictions[test_index] = (scores[test_index] >= 0.5).astype(int)

    model_metrics = _report("LightGBM: leave-one-village-out", y, predictions, scores)

    # Plant cane and ratoon are different shapes of the same crop, and an
    # overall score can hide a model that finds every established field
    # and misses every new planting. A real plot showed plant cane
    # sitting at bare-soil NDVI for months; if that case is being missed,
    # it has to be visible here rather than averaged away.
    if "cane_type" in frame.columns:
        print("\n--- recall by cane type ---")
        for cane_type in ("plant", "ratoon"):
            mask = (frame["cane_type"] == cane_type).to_numpy()
            positives = int(y[mask].sum())
            if positives == 0:
                print(f"  {cane_type:7} no labelled fields")
                continue
            found = int(predictions[mask & (y == 1)].sum())
            print(f"  {cane_type:7} {found}/{positives} found  (recall {found / positives:.2f})")
        if ((frame["cane_type"] == "plant").sum() < 3) or ((frame["cane_type"] == "ratoon").sum() < 3):
            print("  too few of one type to conclude anything from these")

    # ---------------------------------------------------------------
    # The verdict, stated plainly so it cannot be skimmed past.
    # ---------------------------------------------------------------
    gain = model_metrics["f1"] - baseline["f1"]
    print(f"\n{'=' * 58}")
    print(f"F1: baseline {baseline['f1']:.3f} -> model {model_metrics['f1']:.3f}  ({gain:+.3f})")
    if len(frame) < MIN_FIELDS_FOR_VERDICT:
        print(f"VERDICT: withheld. {len(frame)} fields is below the {MIN_FIELDS_FOR_VERDICT}")
        print("         a fold needs to fit anything at all. Read the numbers")
        print("         above as a pipeline check, not as performance.")
    elif gain <= 0.02:
        print("VERDICT: the model does not beat a one-line threshold.")
        print("         Ship the threshold. It is simpler and easier to defend.")
    else:
        print("VERDICT: the model earns its place.")
    print("=" * 58)

    final = LGBMClassifier(
        n_estimators=300, learning_rate=0.05, num_leaves=8, min_child_samples=5, verbose=-1
    )
    final.fit(X, y)
    args.model_out.parent.mkdir(parents=True, exist_ok=True)
    final.booster_.save_model(str(args.model_out))
    print(f"\nmodel written to {args.model_out}")

    importance = sorted(zip(features, final.feature_importances_), key=lambda pair: -pair[1])
    if not any(value for _, value in importance):
        # Every importance zero means the trees never split — too few
        # samples for min_child_samples. Whatever the scores above said,
        # it came from the class prior, not from any feature.
        print("\nNO FEATURE WAS USED. The trees never split, so nothing was learned;")
        print("any score above came from the class balance. Add labelled fields.")
        return
    print("\ntop features:")
    for name, value in importance[:8]:
        print(f"  {name:22} {value}")


if __name__ == "__main__":
    main()
