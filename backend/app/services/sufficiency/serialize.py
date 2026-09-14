"""JSON forms of model confidence, decision sufficiency and sub-signals, for
persistence in JSONB columns and for API responses. Pure."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date
from enum import Enum

from app.services.risk.models import ModelConfidence, SubSignal
from app.services.sufficiency.evaluate import DecisionSufficiency

__all__ = ["model_confidence_json", "sub_signals_json", "sufficiency_json"]


def _plain(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_plain(v) for v in value]
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {str(_plain(k)): _plain(v) for k, v in value.items()}
    if is_dataclass(value):
        return _plain(asdict(value))
    return value


def model_confidence_json(model_confidence: ModelConfidence) -> dict:
    return _plain(model_confidence)


def sufficiency_json(sufficiency: DecisionSufficiency) -> dict:
    return _plain(sufficiency)


def sub_signals_json(signals: list[SubSignal]) -> list[dict]:
    return _plain(signals)
