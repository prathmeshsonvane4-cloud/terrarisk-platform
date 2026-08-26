"""Train and honestly validate the sugarcane classifier.

    python ml/train.py features.csv

WHAT THIS DELIBERATELY DOES
---------------------------
Reports a BASELINE FIRST. A single threshold on minimum NDVI already
separates sugarcane from annual crops fairly well, because cane runs
12-18 months and never goes bare. If LightGBM cannot beat that
threshold, the honest conclusion is that we built a threshold with extra
steps — and that conclusion should be impossible to avoid seeing.

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

NON_FEATURE_COLUMNS = {"field_id", "label", "village"}


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
        and not column.startswith(("ndvi_2", "vv_2", "vh_2"))
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
    parser.add_argument("--threshold", type=float, default=0.30, help="Baseline min-NDVI cutoff")
    parser.add_argument("--model-out", type=Path, default=Path("ml/sugarcane_model.txt"))
    args = parser.parse_args()

    frame = pd.read_csv(args.features)
    frame = frame.dropna(subset=["min_ndvi"])
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
    baseline_pred = (frame["min_ndvi"] >= args.threshold).astype(int).to_numpy()
    baseline = _report(
        f"BASELINE: min_ndvi >= {args.threshold}", y, baseline_pred, frame["min_ndvi"].to_numpy()
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

    # ---------------------------------------------------------------
    # The verdict, stated plainly so it cannot be skimmed past.
    # ---------------------------------------------------------------
    gain = model_metrics["f1"] - baseline["f1"]
    print(f"\n{'=' * 58}")
    print(f"F1: baseline {baseline['f1']:.3f} -> model {model_metrics['f1']:.3f}  ({gain:+.3f})")
    if gain <= 0.02:
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
    print("\ntop features:")
    for name, value in importance[:8]:
        print(f"  {name:22} {value}")


if __name__ == "__main__":
    main()
