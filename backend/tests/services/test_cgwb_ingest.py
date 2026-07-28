"""Tests for the CGWB ingestion download abstraction and parser
(ticket M3-003). No live network calls: `parse_envelope()` is tested
against fixture JSON shaped exactly like the real data.gov.in response
captured during this ticket's interactive verification
(docs/Water_Intelligence_CGWB_Ingestion_Design.md); the download
client's retry/error behavior is tested against `httpx.MockTransport`,
httpx's own built-in test seam — no real HTTP request is made anywhere
in this file.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from app.services.hydrology.cgwb_ingest import (
    CgwbDataGovInClient,
    CgwbFieldMapping,
    CgwbRecordError,
    CgwbSourceConfig,
    parse_envelope,
)

# A generic field mapping using descriptive, deliberately non-CGWB-branded
# names — the real field names were not confirmed during this ticket (see
# the module's own docstring), so tests must not imply a specific,
# unverified schema is correct.
_FIELD_MAPPING = CgwbFieldMapping(
    block_identifier_field="assessment_unit",
    category_field="stage_category",
    assessment_period_field="period_label",
    state_field="state_name",
)

# A placeholder fixture URL — ticket M3-004 requires source_url to be
# threaded through explicitly (see CgwbFetchResult's own docstring), not
# a real endpoint any of these offline tests actually contact.
_SOURCE_URL = "https://example.gov.in/backend/dataapi/v1/resource/test-fixture"


def _envelope(records: list[dict], **overrides) -> dict:
    base = {
        "title": "Sample Assessment Unit Categorization",
        "total": len(records),
        "count": len(records),
        "limit": "10",
        "offset": "0",
        "updated": 1700000000,
        "status": "ok",
        "field": [
            {"name": "Assessment Unit", "id": "assessment_unit", "type": "keyword"},
            {"name": "Category", "id": "stage_category", "type": "keyword"},
            {"name": "Period", "id": "period_label", "type": "keyword"},
        ],
        "records": records,
    }
    base.update(overrides)
    return base


class TestParseEnvelopeHappyPath:
    def test_valid_records_are_all_parsed(self):
        envelope = _envelope(
            [
                {"assessment_unit": "Block A", "stage_category": "Safe", "period_label": "2023", "state_name": "State One"},
                {"assessment_unit": "Block B", "stage_category": "Critical", "period_label": "2023", "state_name": "State One"},
            ]
        )

        result = parse_envelope(envelope, _FIELD_MAPPING, source_url=_SOURCE_URL)

        assert len(result.observations) == 2
        assert result.errors == []
        assert result.observations[0].block_identifier == "Block A"
        assert result.observations[0].category == "Safe"
        assert result.observations[0].assessment_period == "2023"
        assert result.observations[0].state == "State One"

    def test_state_field_is_optional_and_defaults_to_none(self):
        mapping_without_state = CgwbFieldMapping(
            block_identifier_field="assessment_unit",
            category_field="stage_category",
            assessment_period_field="period_label",
        )
        envelope = _envelope([{"assessment_unit": "Block A", "stage_category": "Safe", "period_label": "2023"}])

        result = parse_envelope(envelope, mapping_without_state, source_url=_SOURCE_URL)

        assert result.observations[0].state is None

    def test_values_are_stripped_of_surrounding_whitespace(self):
        envelope = _envelope([{"assessment_unit": "  Block A  ", "stage_category": " Safe ", "period_label": " 2023 "}])
        result = parse_envelope(envelope, _FIELD_MAPPING, source_url=_SOURCE_URL)
        assert result.observations[0].block_identifier == "Block A"
        assert result.observations[0].category == "Safe"

    def test_raw_record_is_preserved_on_the_observation(self):
        raw = {"assessment_unit": "Block A", "stage_category": "Safe", "period_label": "2023", "extra_column": "value"}
        result = parse_envelope(_envelope([raw]), _FIELD_MAPPING, source_url=_SOURCE_URL)
        assert result.observations[0].raw == raw


class TestMalformedRecords:
    def test_missing_required_field_is_collected_as_an_error_not_raised(self):
        envelope = _envelope([{"assessment_unit": "Block A", "stage_category": "Safe"}])  # no period_label

        result = parse_envelope(envelope, _FIELD_MAPPING, source_url=_SOURCE_URL)

        assert result.observations == []
        assert len(result.errors) == 1
        assert "assessment_period" in result.errors[0].reason

    def test_empty_string_field_is_treated_as_missing(self):
        envelope = _envelope([{"assessment_unit": "Block A", "stage_category": "", "period_label": "2023"}])
        result = parse_envelope(envelope, _FIELD_MAPPING, source_url=_SOURCE_URL)
        assert result.observations == []
        assert "category" in result.errors[0].reason

    def test_whitespace_only_field_is_treated_as_missing(self):
        envelope = _envelope([{"assessment_unit": "   ", "stage_category": "Safe", "period_label": "2023"}])
        result = parse_envelope(envelope, _FIELD_MAPPING, source_url=_SOURCE_URL)
        assert result.observations == []

    def test_non_string_field_value_is_rejected(self):
        envelope = _envelope([{"assessment_unit": "Block A", "stage_category": 42, "period_label": "2023"}])
        result = parse_envelope(envelope, _FIELD_MAPPING, source_url=_SOURCE_URL)
        assert result.observations == []
        assert isinstance(result.errors[0], CgwbRecordError)

    def test_record_that_is_not_an_object_is_rejected(self):
        envelope = _envelope(["not-a-record"])
        result = parse_envelope(envelope, _FIELD_MAPPING, source_url=_SOURCE_URL)
        assert result.observations == []
        assert "not an object" in result.errors[0].reason

    def test_one_malformed_record_does_not_discard_the_rest_of_the_batch(self):
        envelope = _envelope(
            [
                {"assessment_unit": "Block A", "stage_category": "Safe", "period_label": "2023"},
                {"assessment_unit": "Block B", "stage_category": "Critical"},  # malformed
                {"assessment_unit": "Block C", "stage_category": "Over-exploited", "period_label": "2023"},
            ]
        )

        result = parse_envelope(envelope, _FIELD_MAPPING, source_url=_SOURCE_URL)

        assert len(result.observations) == 2
        assert len(result.errors) == 1
        assert {o.block_identifier for o in result.observations} == {"Block A", "Block C"}

    def test_missing_records_key_entirely_produces_zero_observations_not_an_error(self):
        envelope = _envelope([])
        del envelope["records"]
        result = parse_envelope(envelope, _FIELD_MAPPING, source_url=_SOURCE_URL)
        assert result.observations == []
        assert result.errors == []


class TestMetadataExtraction:
    def test_all_metadata_fields_are_extracted(self):
        envelope = _envelope(
            [{"assessment_unit": "Block A", "stage_category": "Safe", "period_label": "2023"}],
            title="Real Dataset Title",
            total=100,
            count=1,
            limit="50",
            offset="0",
            updated=1700000000,
        )

        result = parse_envelope(envelope, _FIELD_MAPPING, source_url=_SOURCE_URL)

        assert result.metadata.title == "Real Dataset Title"
        assert result.metadata.total == 100
        assert result.metadata.count == 1
        assert result.metadata.limit == 50
        assert result.metadata.offset == 0
        assert result.metadata.updated_at == datetime.fromtimestamp(1700000000, tz=timezone.utc)

    def test_string_typed_limit_and_offset_are_coerced_to_int(self):
        """Directly observed on the real data.gov.in response during
        this ticket: limit/offset are returned as strings even though
        total/count are real ints — a real inconsistency, not assumed."""
        envelope = _envelope([], limit="25", offset="75")
        result = parse_envelope(envelope, _FIELD_MAPPING, source_url=_SOURCE_URL)
        assert result.metadata.limit == 25
        assert result.metadata.offset == 75
        assert isinstance(result.metadata.limit, int)

    def test_missing_total_defaults_to_zero_not_an_error(self):
        envelope = _envelope([])
        del envelope["total"]
        result = parse_envelope(envelope, _FIELD_MAPPING, source_url=_SOURCE_URL)
        assert result.metadata.total == 0

    def test_missing_updated_timestamp_yields_none(self):
        envelope = _envelope([])
        del envelope["updated"]
        result = parse_envelope(envelope, _FIELD_MAPPING, source_url=_SOURCE_URL)
        assert result.metadata.updated_at is None

    def test_unparseable_updated_timestamp_yields_none_not_a_crash(self):
        envelope = _envelope([], updated="not-a-timestamp")
        result = parse_envelope(envelope, _FIELD_MAPPING, source_url=_SOURCE_URL)
        assert result.metadata.updated_at is None


class TestDeterministicParsing:
    def test_parsing_the_same_envelope_twice_produces_equal_results(self):
        envelope = _envelope(
            [
                {"assessment_unit": "Block A", "stage_category": "Safe", "period_label": "2023"},
                {"assessment_unit": "Block B", "stage_category": "Critical", "period_label": "2023"},
            ]
        )

        first = parse_envelope(envelope, _FIELD_MAPPING, source_url=_SOURCE_URL)
        second = parse_envelope(envelope, _FIELD_MAPPING, source_url=_SOURCE_URL)

        assert first == second


class TestCgwbDataGovInClient:
    """Retry/error behavior tested against httpx.MockTransport — httpx's
    own built-in test seam. No real network call is made anywhere here.

    `httpx.Client` (the real class) is captured into `_RealHttpxClient`
    once, at import time, before any test monkeypatches
    `cgwb_ingest.httpx.Client` — `cgwb_ingest` imports the `httpx` module
    itself (not just the `Client` name), so `cgwb_ingest.httpx` and this
    file's own `httpx` are literally the same module object; patching
    `.Client` on it is global, and a replacement handler that calls
    `httpx.Client(...)` internally would recursively call the patched
    version. Using the real class captured before any patching avoids
    that.
    """

    def test_successful_response_is_returned_as_parsed_json(self, monkeypatch):
        real_httpx_client = httpx.Client

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["api-key"] == "test-key"
            return httpx.Response(200, json={"status": "ok", "records": []})

        import app.services.hydrology.cgwb_ingest as module

        monkeypatch.setattr(
            module.httpx, "Client", lambda *a, **kw: real_httpx_client(transport=httpx.MockTransport(handler))
        )

        client = CgwbDataGovInClient()
        config = CgwbSourceConfig(resource_id="abc-123", api_key="test-key", field_mapping=_FIELD_MAPPING)
        result = client.fetch_page(config, limit=10, offset=0)

        assert result == {"status": "ok", "records": []}

    def test_http_error_response_is_raised_immediately_not_retried(self, monkeypatch):
        real_httpx_client = httpx.Client
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            return httpx.Response(400, json={"error": "missing api-key"})

        import app.services.hydrology.cgwb_ingest as module

        monkeypatch.setattr(
            module.httpx, "Client", lambda *a, **kw: real_httpx_client(transport=httpx.MockTransport(handler))
        )

        client = CgwbDataGovInClient()
        config = CgwbSourceConfig(resource_id="abc-123", api_key="bad-key", field_mapping=_FIELD_MAPPING)
        with pytest.raises(httpx.HTTPStatusError):
            client.fetch_page(config, limit=10, offset=0)

        assert call_count["n"] == 1  # not retried

    def test_transport_error_is_retried_up_to_the_bounded_limit(self, monkeypatch):
        real_httpx_client = httpx.Client
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            raise httpx.ConnectError("connection refused", request=request)

        import app.services.hydrology.cgwb_ingest as module

        monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)  # skip real backoff delay in tests
        monkeypatch.setattr(
            module.httpx, "Client", lambda *a, **kw: real_httpx_client(transport=httpx.MockTransport(handler))
        )

        client = CgwbDataGovInClient()
        config = CgwbSourceConfig(resource_id="abc-123", api_key="test-key", field_mapping=_FIELD_MAPPING)
        with pytest.raises(httpx.ConnectError):
            client.fetch_page(config, limit=10, offset=0)

        assert call_count["n"] == 3  # bounded: exactly _MAX_RETRY_ATTEMPTS

    def test_transport_error_that_recovers_on_retry_succeeds(self, monkeypatch):
        real_httpx_client = httpx.Client
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            if call_count["n"] < 2:
                raise httpx.ConnectError("connection refused", request=request)
            return httpx.Response(200, json={"status": "ok", "records": []})

        import app.services.hydrology.cgwb_ingest as module

        monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
        monkeypatch.setattr(
            module.httpx, "Client", lambda *a, **kw: real_httpx_client(transport=httpx.MockTransport(handler))
        )

        client = CgwbDataGovInClient()
        config = CgwbSourceConfig(resource_id="abc-123", api_key="test-key", field_mapping=_FIELD_MAPPING)
        result = client.fetch_page(config, limit=10, offset=0)

        assert result == {"status": "ok", "records": []}
        assert call_count["n"] == 2
