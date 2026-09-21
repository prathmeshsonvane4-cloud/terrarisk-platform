"""What the label set contains, and what it still needs.

    python ml/dataset_status.py

Run it after every batch of labels. It answers one question: can anything
be claimed from this data yet, and if not, what is missing.

WHY GATES RATHER THAN A PROGRESS BAR
------------------------------------
A classifier will happily produce a number from five fields. That number
is the class prior wearing a decimal point, and once it has been said out
loud to a bank or an employer it is very hard to take back. The gates
below are the points at which a statement becomes defensible, so the
honest answer to "how is the model doing" is available before anyone
asks.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

# Matches train.py's own MIN_FIELDS_FOR_VERDICT: below this the
# leave-one-village-out folds are too small to fit anything.
MIN_FIELDS_FOR_VERDICT = 30

# What a claim outside this project should rest on. Not a law of
# statistics — a judgement that 30 of each class over 4 villages is the
# least that can survive "does it work on a village you have not seen?".
TARGET_PER_CLASS = 30
TARGET_VILLAGES = 4
TARGET_PER_CANE_TYPE = 3

# One village dominating means the folds are really one big fold, and the
# score reflects that village's soil and irrigation rather than the crop.
MAX_VILLAGE_SHARE = 0.4


def gate(passed: bool, title: str, detail: str) -> bool:
    print(f"  [{'x' if passed else ' '}] {title}")
    if detail:
        print(f"      {detail}")
    return passed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=Path("ml/labels.geojson"))
    parser.add_argument("--features", type=Path, default=Path("ml/features.csv"))
    args = parser.parse_args()

    if not args.path.exists():
        print(f"No labels yet at {args.path}.")
        print("Collect fields, then: python ml/add_labels_bulk.py ml/incoming/<date>.txt")
        return

    fields = [f["properties"] for f in json.loads(args.path.read_text(encoding="utf-8"))["features"]]
    cane = [f for f in fields if f["label"] == 1]
    other = [f for f in fields if f["label"] != 1]
    villages = Counter(f["village"] for f in fields)
    cane_types = Counter(f.get("cane_type", "") for f in cane)
    sources = Counter(f.get("source", "") for f in fields)

    print(f"LABELS  {len(fields)} fields — {len(cane)} sugarcane, {len(other)} other")
    print(f"        {len(villages)} village(s): " + ", ".join(f"{v} ({n})" for v, n in villages.most_common()))
    print(f"        cane type: {cane_types.get('plant', 0)} plant, {cane_types.get('ratoon', 0)} ratoon")
    print(f"        evidence: " + ", ".join(f"{s or 'unrecorded'} {n}" for s, n in sources.most_common()))
    if other:
        crops = Counter(f.get("crop", "") or "unspecified" for f in other)
        print(f"        other crops: " + ", ".join(f"{c} ({n})" for c, n in crops.most_common()))

    extracted = 0
    if args.features.exists():
        extracted = max(0, sum(1 for _ in args.features.open(encoding="utf-8")) - 1)
    print(f"\nFEATURES {extracted} of {len(fields)} fields extracted from satellite data")
    if extracted < len(fields):
        print(f"        run: python ml/extract_features.py {args.path} {args.features}")

    print("\nGATES")
    gate(len(fields) >= 1, "Pipeline can run", f"{len(fields)} field(s) labelled")
    ready_for_verdict = gate(
        len(fields) >= MIN_FIELDS_FOR_VERDICT and len(villages) >= 2,
        f"Training can report a verdict ({MIN_FIELDS_FOR_VERDICT}+ fields, 2+ villages)",
        f"have {len(fields)} fields across {len(villages)} village(s)",
    )

    shortfalls = []
    if len(cane) < TARGET_PER_CLASS:
        shortfalls.append(f"{TARGET_PER_CLASS - len(cane)} more sugarcane")
    if len(other) < TARGET_PER_CLASS:
        shortfalls.append(f"{TARGET_PER_CLASS - len(other)} more non-sugarcane")
    if len(villages) < TARGET_VILLAGES:
        shortfalls.append(f"{TARGET_VILLAGES - len(villages)} more village(s)")
    for cane_type in ("plant", "ratoon"):
        missing = TARGET_PER_CANE_TYPE - cane_types.get(cane_type, 0)
        if missing > 0:
            shortfalls.append(f"{missing} more {cane_type} cane")
    biggest = villages.most_common(1)[0] if villages else ("", 0)
    if fields and biggest[1] / len(fields) > MAX_VILLAGE_SHARE:
        shortfalls.append(f"spread beyond {biggest[0]} ({biggest[1]}/{len(fields)} of all fields)")

    gate(
        not shortfalls,
        "Result can be shown outside this project",
        "still needed: " + "; ".join(shortfalls) if shortfalls else "nothing — the set meets every target",
    )

    print()
    if not ready_for_verdict:
        print("NEXT: keep collecting. Training now is a pipeline check, not a measurement —")
        print("      train.py will say so rather than print a score you could quote.")
    elif shortfalls:
        print("NEXT: train.py will give a real leave-one-village-out score. Treat it as")
        print("      provisional until the last gate closes.")
    else:
        print("NEXT: train, and report the number with its confusion matrix and the")
        print("      villages it was tested on.")

    if other and len(cane) / len(fields) > 0.6:
        print("\nWARNING: mostly sugarcane. Real districts are not, so a model tuned on")
        print("         this balance will over-call cane in the field.")
    if not other:
        print("\nWARNING: every field is sugarcane. A classifier cannot learn what cane is")
        print("         without fields that are not cane — collect both from the start.")


if __name__ == "__main__":
    main()
