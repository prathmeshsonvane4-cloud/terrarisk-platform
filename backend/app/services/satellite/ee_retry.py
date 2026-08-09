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
from typing import Callable, TypeVar

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
