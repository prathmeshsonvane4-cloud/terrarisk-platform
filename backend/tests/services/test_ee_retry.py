"""Tests for the Earth Engine transient-failure retry wrapper.

`time.sleep` is patched out in every test. The backoff schedule is real
(2/4/8/16s) and waiting through it would make the suite unusable, but
the delays are still asserted where they matter, so patching hides no
behaviour.
"""

from __future__ import annotations

import ee
import pytest

from app.services.satellite import ee_retry
from app.services.satellite.ee_retry import with_ee_retry


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Records the delays that would have been slept instead of sleeping."""
    slept: list[float] = []
    monkeypatch.setattr(ee_retry.time, "sleep", slept.append)
    return slept


class TestTransientFailures:
    def test_returns_the_result_once_a_retry_succeeds(self) -> None:
        attempts = {"count": 0}

        def flaky() -> str:
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise ee.EEException("Too many concurrent aggregations.")
            return "payload"

        assert with_ee_retry(flaky, description="test") == "payload"
        assert attempts["count"] == 3

    def test_backs_off_exponentially_between_attempts(self, _no_sleep: list[float]) -> None:
        def always_throttled() -> str:
            raise ee.EEException("Too many concurrent aggregations.")

        with pytest.raises(ee.EEException):
            with_ee_retry(always_throttled, description="test")

        # Four waits before the fifth and final attempt.
        assert len(_no_sleep) == 4
        # Each nominal delay doubles (2/4/8/16); jitter adds up to 25%, so
        # the assertion brackets each rather than pinning an exact value.
        for index, base in enumerate([2.0, 4.0, 8.0, 16.0]):
            assert base <= _no_sleep[index] <= base * 1.25

    def test_stops_after_the_attempt_limit_and_reraises(self) -> None:
        attempts = {"count": 0}

        def always_throttled() -> str:
            attempts["count"] += 1
            raise ee.EEException("Too many concurrent aggregations.")

        with pytest.raises(ee.EEException, match="Too many concurrent aggregations"):
            with_ee_retry(always_throttled, description="test")
        assert attempts["count"] == ee_retry._MAX_ATTEMPTS

    @pytest.mark.parametrize(
        "message",
        [
            "Too many concurrent aggregations.",
            "Too Many Requests",
            "Quota exceeded for this project",
            "Earth Engine backend error",
            "Computation timed out",
        ],
    )
    def test_treats_the_documented_throttle_messages_as_transient(self, message: str) -> None:
        attempts = {"count": 0}

        def flaky() -> str:
            attempts["count"] += 1
            if attempts["count"] < 2:
                raise ee.EEException(message)
            return "ok"

        assert with_ee_retry(flaky, description="test") == "ok"
        assert attempts["count"] == 2


class TestNonTransientFailures:
    """Retrying these would spend quota to reach the same failure, and
    would bury the real cause behind 30 seconds of backoff."""

    @pytest.mark.parametrize(
        "message",
        [
            "Image.load: Asset 'users/nobody/missing' not found.",
            "Permission denied on project geoai-flood-analytics.",
            "Invalid GeoJSON geometry.",
        ],
    )
    def test_raises_immediately_without_retrying(self, message: str, _no_sleep: list[float]) -> None:
        attempts = {"count": 0}

        def broken() -> str:
            attempts["count"] += 1
            raise ee.EEException(message)

        with pytest.raises(ee.EEException):
            with_ee_retry(broken, description="test")

        assert attempts["count"] == 1
        assert _no_sleep == []

    def test_does_not_swallow_non_earth_engine_exceptions(self) -> None:
        def broken() -> str:
            raise ValueError("a bug in our own code, not a throttle")

        with pytest.raises(ValueError, match="a bug in our own code"):
            with_ee_retry(broken, description="test")


class TestSuccessPath:
    def test_calls_the_operation_once_when_it_succeeds(self, _no_sleep: list[float]) -> None:
        attempts = {"count": 0}

        def fine() -> int:
            attempts["count"] += 1
            return 42

        assert with_ee_retry(fine, description="test") == 42
        assert attempts["count"] == 1
        assert _no_sleep == []
