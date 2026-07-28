"""CGWB groundwater-category ingestion — download abstraction and parser
skeleton only (ticket M3-003). No persistence, no API, no scheduler, no
engine changes — see this module's own scope note below.

=====================================================================
WHAT THIS MODULE IS BUILT AGAINST, AND WHY
=====================================================================

Ticket M3-002 (research spike) and M3-003's own interactive verification
(docs/Water_Intelligence_CGWB_Ingestion_Design.md) confirmed exactly ONE
thing with full confidence: **data.gov.in's REST API envelope shape**.
A live request during M3-003 —

    GET https://www.data.gov.in/backend/dataapi/v1/resource/{resource_id}
        ?format=json&api-key={key}

— returned a real HTTP 200 with a JSON body shaped like:

    {"field": [{"name": ..., "id": ..., "type": ...}, ...],
     "records": [{"<field_id>": "<value>", ...}, ...],
     "total": N, "count": N, "limit": N, "offset": N,
     "title": "...", "created": <epoch>, "updated": <epoch>,
     "status": "ok"}

A request to the same endpoint without `api-key` returned HTTP 400,
confirming the key is required, not optional.

What was NOT verified: which specific `resource_id` on data.gov.in
actually holds block/district-level CGWB category-and-Stage-of-Extraction
data. The one ground-water resource inspected directly during this
ticket ("Category-wise Details of Annual Ground Water Recharge,
Extraction and Stage of Ground Water Extraction...") turned out to be a
413-byte, 5-field, national-aggregate summary table — not block-level,
and explicitly disqualified for this purpose (see the design doc).

**This module therefore does not hardcode any CGWB-specific field name.**
`CgwbSourceConfig`/`CgwbFieldMapping` accept the resource ID and field
mapping as configuration, supplied once a human has manually confirmed
the correct resource on the portal — exactly what "do not assume any API
or file format" requires. Everything here is deliberately generic enough
to be correct against any data.gov.in resource sharing this verified
envelope shape, for any Indian state — no geography, customer, or sector
assumption is encoded anywhere in this file.

Explicitly out of scope for this ticket (see the design doc's own Step 3
gate): persistence into `cgwb_groundwater_observation` (a later ticket),
any API endpoint, any scheduler/background trigger, any change to an
engine or the database schema.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

# The one piece of this integration verified directly during ticket
# M3-003 — see the module docstring. Not a guess.
DATA_GOV_IN_BASE_URL = "https://www.data.gov.in/backend/dataapi/v1/resource"

_DEFAULT_TIMEOUT_SECONDS = 15.0
_DEFAULT_PAGE_LIMIT = 100
_MAX_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 1.0

# Generic, platform-level identification — no product/customer branding,
# per this ticket's explicit "stay generic" requirement.
_USER_AGENT = "WaterIntelligence-CGWBIngest/0.1"


@dataclass(frozen=True)
class CgwbFieldMapping:
    """Which raw field IDs (from a data.gov.in resource's own `field`
    list) correspond to the concepts `cgwb_groundwater_observation`
    needs. Deliberately NOT hardcoded to any specific dataset's real
    field names — those were not confirmed during this ticket (see
    module docstring) — a human supplies this once the correct
    `resource_id` is confirmed on the portal.
    """

    block_identifier_field: str
    category_field: str
    assessment_period_field: str
    state_field: str | None = None


@dataclass(frozen=True)
class CgwbSourceConfig:
    """Configuration for one data.gov.in resource fetch. `resource_id`
    and `api_key` are NOT defaulted to any real value here — supplying
    them is the explicit human-verification step this ticket's own gate
    requires before any live fetch is attempted.
    """

    resource_id: str
    api_key: str
    field_mapping: CgwbFieldMapping
    base_url: str = DATA_GOV_IN_BASE_URL
    page_limit: int = _DEFAULT_PAGE_LIMIT


@dataclass(frozen=True)
class CgwbRawObservation:
    """One successfully parsed and validated record — the pure-Python
    shape a later ticket's persistence layer would map onto
    `CgwbGroundwaterObservation` (M0-006). Deliberately a different type
    from that ORM model: this module has no database dependency at all.
    """

    block_identifier: str
    category: str
    assessment_period: str
    state: str | None
    raw: dict


@dataclass(frozen=True)
class CgwbRecordError:
    """One record that failed validation — collected, not raised, so one
    malformed row never discards an otherwise-good batch (this
    codebase's established "persist what's known" resilience
    philosophy, applied here to parsing rather than persistence)."""

    reason: str
    raw: dict


@dataclass(frozen=True)
class CgwbFetchMetadata:
    """Envelope-level metadata extracted alongside the parsed records —
    exactly the fields directly observed on a real data.gov.in response
    during this ticket (title/total/count/limit/offset/updated_at)."""

    title: str | None
    total: int
    count: int
    limit: int
    offset: int
    updated_at: datetime | None


@dataclass(frozen=True)
class CgwbFetchResult:
    """`source_url` (ticket M3-004): the exact URL the records in this
    result were fetched from — required because
    `CgwbGroundwaterObservation.source_url` is a NOT NULL column
    (`app/models/cgwb.py`, M0-006's own "every ingested value must be
    able to point at where it was sourced" provenance requirement).
    Threaded through from the caller of `parse_envelope()`, which already
    knows the exact URL used for the fetch — never guessed or
    reconstructed after the fact."""

    metadata: CgwbFetchMetadata
    observations: list[CgwbRawObservation]
    source_url: str
    errors: list[CgwbRecordError] = field(default_factory=list)


class CgwbDataGovInClient:
    """Download abstraction for data.gov.in's REST API — the one
    mechanism verified live during ticket M3-003. Retries transport-level
    failures (timeout, connection error) with a bounded, small number of
    attempts and exponential backoff; never retries an HTTP error
    response (a 400/401/etc. is a configuration problem, not a transient
    fault, and retrying it would never succeed — confirmed directly:
    requesting the verified endpoint without an api-key returned 400,
    not something backoff would fix).
    """

    def __init__(self, timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS) -> None:
        self._timeout_seconds = timeout_seconds

    def fetch_page(self, config: CgwbSourceConfig, *, limit: int, offset: int) -> dict:
        """Fetch one page of raw records from the configured resource.
        Returns the raw JSON envelope, unparsed — parsing is a separate,
        pure function below, kept independent of any network call so it
        can be tested without one.
        """
        url = f"{config.base_url}/{config.resource_id}"
        params = {"format": "json", "api-key": config.api_key, "limit": limit, "offset": offset}

        last_error: Exception | None = None
        for attempt in range(1, _MAX_RETRY_ATTEMPTS + 1):
            try:
                logger.info(
                    "cgwb_fetch_attempt",
                    extra={"resource_id": config.resource_id, "offset": offset, "limit": limit, "attempt": attempt},
                )
                with httpx.Client(timeout=self._timeout_seconds, headers={"User-Agent": _USER_AGENT}) as client:
                    response = client.get(url, params=params)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as exc:
                # Not retried — a 4xx/5xx response is a configuration or
                # server-side problem backoff cannot fix (verified: a
                # missing api-key produces 400 deterministically, not
                # intermittently).
                logger.error(
                    "cgwb_fetch_http_error",
                    extra={"resource_id": config.resource_id, "status_code": exc.response.status_code},
                )
                raise
            except httpx.TransportError as exc:
                last_error = exc
                logger.warning(
                    "cgwb_fetch_transport_error_retrying",
                    extra={"resource_id": config.resource_id, "attempt": attempt, "error": str(exc)},
                )
                if attempt < _MAX_RETRY_ATTEMPTS:
                    time.sleep(_RETRY_BACKOFF_SECONDS * attempt)

        assert last_error is not None
        logger.error(
            "cgwb_fetch_exhausted_retries",
            extra={"resource_id": config.resource_id, "attempts": _MAX_RETRY_ATTEMPTS},
        )
        raise last_error


def parse_envelope(raw_envelope: dict, field_mapping: CgwbFieldMapping, *, source_url: str) -> CgwbFetchResult:
    """Parse and validate one raw data.gov.in JSON envelope (as returned
    by `CgwbDataGovInClient.fetch_page`, or an equivalent fixture in
    tests — this function has no network dependency of its own). Every
    record is validated independently; a malformed record is collected
    as a `CgwbRecordError`, never raised, so one bad row cannot discard
    an otherwise-good page.

    `source_url` (ticket M3-004): the exact URL these records came from —
    the caller already knows it (it built the request), so it is passed
    in explicitly rather than reconstructed or guessed here.
    """
    metadata = _extract_metadata(raw_envelope)

    observations: list[CgwbRawObservation] = []
    errors: list[CgwbRecordError] = []
    for raw_record in raw_envelope.get("records", []):
        result = _validate_record(raw_record, field_mapping)
        if isinstance(result, CgwbRecordError):
            errors.append(result)
        else:
            observations.append(result)

    logger.info(
        "cgwb_envelope_parsed",
        extra={"parsed": len(observations), "errors": len(errors), "total": metadata.total},
    )
    return CgwbFetchResult(metadata=metadata, observations=observations, source_url=source_url, errors=errors)


def _extract_metadata(raw_envelope: dict) -> CgwbFetchMetadata:
    updated_epoch = raw_envelope.get("updated")
    updated_at = None
    if isinstance(updated_epoch, (int, float)):
        updated_at = datetime.fromtimestamp(updated_epoch, tz=timezone.utc)

    return CgwbFetchMetadata(
        title=raw_envelope.get("title"),
        total=_coerce_int(raw_envelope.get("total"), default=0),
        count=_coerce_int(raw_envelope.get("count"), default=0),
        limit=_coerce_int(raw_envelope.get("limit"), default=0),
        offset=_coerce_int(raw_envelope.get("offset"), default=0),
        updated_at=updated_at,
    )


def _coerce_int(value, *, default: int) -> int:
    """The verified envelope mixes real ints (`total`, `count`) with
    string-typed ints (`limit`, `offset` were observed as strings, e.g.
    `"limit": "10"`) — coerced here rather than assumed, since that
    inconsistency was directly observed, not guessed at."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _validate_record(raw_record: dict, field_mapping: CgwbFieldMapping) -> CgwbRawObservation | CgwbRecordError:
    if not isinstance(raw_record, dict):
        return CgwbRecordError(reason="record is not an object", raw={"value": raw_record})

    block_identifier = raw_record.get(field_mapping.block_identifier_field)
    category = raw_record.get(field_mapping.category_field)
    assessment_period = raw_record.get(field_mapping.assessment_period_field)
    state = raw_record.get(field_mapping.state_field) if field_mapping.state_field else None

    missing = [
        name
        for name, value in (
            ("block_identifier", block_identifier),
            ("category", category),
            ("assessment_period", assessment_period),
        )
        if not value or not isinstance(value, str) or not value.strip()
    ]
    if missing:
        return CgwbRecordError(reason=f"missing or empty required field(s): {', '.join(missing)}", raw=raw_record)

    return CgwbRawObservation(
        block_identifier=block_identifier.strip(),
        category=category.strip(),
        assessment_period=assessment_period.strip(),
        state=state.strip() if isinstance(state, str) and state.strip() else None,
        raw=raw_record,
    )
