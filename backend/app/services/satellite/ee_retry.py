"""Retry wrapper for Earth Engine `getInfo()` calls.

WHY THIS EXISTS
---------------
Earth Engine answers HTTP 429 "Too many concurrent aggregations" when a
project exceeds its concurrent-aggregation ceiling. That is a transient
back-pressure signal, not a rejection of the query: the identical call
succeeds moments later.

Before this module there was no retry anywhere across thirteen
`getInfo()` call sites, so a single 429 at any point aborted the whole
report. That is a bad failure shape for two reasons:

  - A water report makes ~8 sequential Earth Engine round trips and
    takes minutes. Failing on the last one throws away every earlier
    call's work AND its quota cost, then the user retries and spends it
    all again — the retry is strictly more expensive than the backoff.
  - One report is itself a burst. `get_rainfall_climatology` alone asks
    for 12 months x 30 years = 360 aggregations inside one request, and
    the seasonal baselines add ~96 periods each. The ceiling is
    reachable from a single user pressing the button once, so treating
    429 as fatal makes ordinary use look broken.

Retries are deliberately limited to transient conditions. A malformed
query, a missing asset or a permissions error is not retried — repeating
those burns quota to arrive at the same failure, and hides the real
cause behind a delay.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any, Callable, Sequence, TypeVar

import ee

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Five attempts over roughly 2+4+8+16 = 30s of backoff. Long enough to
# outlast the concurrency bursts we actually cause (one report's own
# calls clearing), short enough that a genuinely saturated project still
# surfaces the failure inside the job's lifetime rather than hanging.
_MAX_ATTEMPTS = 5
_BASE_DELAY_SECONDS = 2.0
_MAX_DELAY_SECONDS = 30.0

# Matched against the exception text, because the Earth Engine Python SDK
# collapses HTTP status into EEException and does not expose the code.
# Kept narrow on purpose — see the module docstring on why non-transient
# failures must not be retried.
_TRANSIENT_MARKERS = (
    "too many concurrent aggregations",
    "too many requests",
    "rate limit",
    "quota exceeded",
    "backend error",
    "internal error",
    "deadline exceeded",
    "service unavailable",
    "computation timed out",
)


def _is_transient(error: Exception) -> bool:
    message = str(error).lower()
    return any(marker in message for marker in _TRANSIENT_MARKERS)


def with_ee_retry(operation: Callable[[], T], *, description: str) -> T:
    """Run `operation`, retrying transient Earth Engine failures with
    exponential backoff and jitter.

    `description` names the call in logs — with thirteen call sites and
    minutes between them, "an EE call was throttled" is not actionable
    on its own.

    Jitter matters here rather than being a formality: without it, two
    reports that collide once go on to retry in lockstep and collide
    again at every subsequent attempt.
    """
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            return operation()
        except ee.EEException as error:
            if not _is_transient(error) or attempt == _MAX_ATTEMPTS:
                raise
            delay = min(_BASE_DELAY_SECONDS * (2 ** (attempt - 1)), _MAX_DELAY_SECONDS)
            delay += random.uniform(0.0, delay * 0.25)
            logger.warning(
                "earth_engine_transient_retry",
                extra={
                    "ee_operation": description,
                    "attempt": attempt,
                    "max_attempts": _MAX_ATTEMPTS,
                    "retry_in_seconds": round(delay, 2),
                    "ee_error": str(error)[:200],
                },
            )
            time.sleep(delay)

    # Unreachable: the loop either returns or raises on the final attempt.
    raise AssertionError("with_ee_retry exhausted its loop without returning or raising")


# How many periods to request in one round trip before splitting.
#
# Measured, not guessed. Against a 1,649 ha catchment reducing Sentinel-2
# NDVI at 10 m, an 18-period request was refused with "Too many
# concurrent aggregations" while 12 succeeded — and 12, 9, 6, 4 and 3 all
# returned in 6-8s, so wall time is dominated by round trips rather than
# by chunk size. 12 is the measured ceiling for THAT catchment, so the
# default sits below it; a larger or more fragmented polygon has a lower
# ceiling still, which is what the halving below is for.
_DEFAULT_CHUNK_SIZE = 8


def fetch_mapped_features(
    items: Sequence[dict],
    build_collection: Callable[[list[dict]], Any],
    *,
    description: str,
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
) -> list[dict]:
    """Evaluate a per-period mapped FeatureCollection in bounded batches,
    returning the concatenated `features` list.

    Earth Engine evaluates `ee.List(periods).map(...)` as that many
    CONCURRENT aggregations inside a single request, so the fan-out — not
    the total work — is what trips the project's concurrency ceiling. A
    36-month series over a large catchment therefore failed outright
    while the same query for one month returned in 1.5s. Splitting the
    list trades one refused request for several accepted ones.

    On a throttle that survives `with_ee_retry`'s backoff, the batch is
    halved and retried rather than abandoned. The ceiling scales with how
    expensive each individual aggregation is, which depends on the
    catchment's area and geometry — so it is a property of the data, not
    a constant this module can know in advance. Halving discovers it per
    call instead of forcing every future catchment to fit one guess.
    """
    features: list[dict] = []
    for offset in range(0, len(items), chunk_size):
        batch = list(items[offset : offset + chunk_size])
        features.extend(_fetch_batch(batch, build_collection, description=description, chunk_size=chunk_size))
    return features


def _fetch_batch(
    batch: list[dict],
    build_collection: Callable[[list[dict]], Any],
    *,
    description: str,
    chunk_size: int,
) -> list[dict]:
    try:
        return with_ee_retry(
            lambda: build_collection(batch).getInfo(),
            description=f"{description}[{len(batch)} periods]",
        )["features"]
    except ee.EEException as error:
        if not _is_transient(error) or len(batch) <= 1:
            raise
        half = max(1, len(batch) // 2)
        logger.warning(
            "earth_engine_chunk_split",
            extra={
                "ee_operation": description,
                "from_chunk_size": len(batch),
                "to_chunk_size": half,
                "ee_error": str(error)[:200],
            },
        )
        return fetch_mapped_features(batch, build_collection, description=description, chunk_size=half)
