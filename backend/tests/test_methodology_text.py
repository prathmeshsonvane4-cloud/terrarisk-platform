from __future__ import annotations

from app.models.enums import RiskFactor
from app.services.reporting.methodology_text import (
    ASSUMPTIONS_AND_LIMITATIONS,
    CLOUD_FILTERING_EXPLANATION,
    CONFIDENCE_EXPLANATION,
    FACTOR_DEFINITIONS,
    INDEX_EXPLANATIONS,
    PERCENTILE_EXPLANATION,
    QUALITY_CONTROL_EXPLANATION,
)


def test_every_risk_factor_has_a_definition():
    for factor in RiskFactor:
        assert factor in FACTOR_DEFINITIONS
        assert len(FACTOR_DEFINITIONS[factor]) > 20


def test_index_explanations_cover_every_index_the_engine_actually_uses():
    for index in ("NDVI", "MNDWI", "NDMI", "VCI", "JRC Global Surface Water", "CHIRPS rainfall"):
        assert index in INDEX_EXPLANATIONS
        assert len(INDEX_EXPLANATIONS[index]) > 20


def test_confidence_explanation_correctly_states_it_is_data_quality_not_risk():
    assert "data quality, not risk" in CONFIDENCE_EXPLANATION


def test_standing_disclaimer_is_the_last_assumption_verbatim():
    assert ASSUMPTIONS_AND_LIMITATIONS[-1] == (
        "This score is decision support for the lending officer. The credit decision remains with the bank."
    )


def test_percentile_and_cloud_filtering_and_quality_control_explanations_are_nonempty():
    assert len(PERCENTILE_EXPLANATION) > 20
    assert len(CLOUD_FILTERING_EXPLANATION) > 20
    assert len(QUALITY_CONTROL_EXPLANATION) > 20
