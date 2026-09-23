"""The training scripts must only ever see numeric, shape-describing
columns — never a date, a name, or a calendar-specific monthly value."""

from __future__ import annotations

import pandas as pd

from train import _feature_columns


def test_text_and_monthly_columns_never_become_features():
    frame = pd.DataFrame(
        {
            "field_id": ["a"], "label": [1], "village": ["Shera"], "crop": ["sugarcane"],
            "planted": ["2026-01"], "cut_date": ["2026-01"], "source": ["owner"],
            "cane_type": ["ratoon"], "sown_year": ["2026"],
            "window_start": ["2025-04"], "window_end": ["2026-09"], "greenup_month": ["2026-03"],
            "ndvi_2026-01": [0.3], "vh_2026-01": [-18.0], "vv_2026-01": [-11.0], "rvi_2026-01": [0.5],
            "longest_green_run": [8], "ndre_mean": [0.3], "rvi_mean": [0.6],
        }
    )
    features = _feature_columns(frame)
    assert features == ["longest_green_run", "ndre_mean", "rvi_mean"]
    # And every one of them converts to a number, which is what crashed.
    frame[features].to_numpy(dtype=float)
