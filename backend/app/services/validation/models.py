"""Result types for the physical validation harness.

Nothing here touches a database, the network, or the filesystem — the same
zero-I/O contract `risk/models.py` and `hydrology/models.py` already
establish for the engines these checks are pointed at.

WHY A REPORT AND NOT AN EXCEPTION
---------------------------------
A failed physical check is not the same kind of event as a malformed
bundle. A malformed bundle means the caller made a programming error and
should get a traceback; an implausible runoff coefficient means the
science is wrong, and the caller needs to know *which* number is wrong,
*how far* outside the expected range it sits, and *what the range was*.
An exception carries one string. A `ValidationReport` carries all of it,
and can carry several findings at once — which matters, because a single
upstream defect (ET too low) usually shows up as several downstream
symptoms (residual too large, storage band wrong) and seeing them
together is what identifies the cause.

The report is returned, not raised. Deciding what to do about an
`ERROR` finding — refuse to persist, persist and flag, fail a CI job — is
a policy question belonging to each caller, and different callers
genuinely need different answers. What is NOT optional is that the
finding is visible: `ValidationReport.failed` exists so no caller can
treat a failing report as passing without writing the word `failed` in
its own source.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

__all__ = [
    "Severity",
    "ValidationFinding",
    "ValidationReport",
]


class Severity(str, Enum):
    """How wrong a finding is, which is a different question from how
    surprising it is.

    `ERROR` is reserved for violations of physics or arithmetic — things
    that cannot be true regardless of geography, season, or calibration.
    Runoff exceeding rainfall is an ERROR. There is no catchment
    anywhere for which it is defensible.

    `WARNING` is for a value that is physically possible but sits outside
    what the literature reports for this agro-climatic zone. It means
    "this is probably a defect, and if it isn't, the reason needs
    writing down" — not "this is definitely wrong". Marathwada in a
    failed monsoon can legitimately produce numbers that look broken.

    `INFO` records a check that ran and had something to say without
    implying fault — most usefully, a check that could NOT run because
    an input was missing. A check that silently skips is indistinguishable
    from a check that passed, and that distinction is the entire point of
    this module.
    """

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class ValidationFinding:
    """One check's outcome.

    `expected` is a human-readable statement of the range or invariant,
    not a machine-comparable bound. It exists so a report reader who has
    never opened this codebase can judge the finding for themselves
    rather than taking "out of range" on trust — the same reasoning
    behind exposing `raw_inputs` on every factor score.
    """

    check: str
    severity: Severity
    message: str
    # The quantity the check looked at, e.g. "runoff_coefficient".
    subject: str
    # None when the check could not run because the input was missing.
    observed: float | None = None
    expected: str = ""
    # Where the range or invariant comes from. Empty for pure arithmetic
    # invariants, which need no citation; required in practice for every
    # literature-derived bound, so a reviewer can check the source rather
    # than the number.
    source: str = ""

    @property
    def is_failure(self) -> bool:
        return self.severity in (Severity.ERROR, Severity.WARNING)


@dataclass(frozen=True)
class ValidationReport:
    """Every finding from one validation pass, plus the context needed to
    interpret them.

    `checks_run` counts checks that actually executed, including ones
    that passed silently and produced no finding. A report with zero
    findings and zero checks run is not a clean bill of health — it is a
    harness that did nothing, and the two must not look alike on a
    dashboard.
    """

    subject: str
    findings: list[ValidationFinding] = field(default_factory=list)
    checks_run: int = 0
    checks_skipped: int = 0

    @property
    def errors(self) -> list[ValidationFinding]:
        return [f for f in self.findings if f.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[ValidationFinding]:
        return [f for f in self.findings if f.severity is Severity.WARNING]

    @property
    def failed(self) -> bool:
        """True when any check produced an ERROR or a WARNING.

        Deliberately not "errors only". A warning here means a number
        sits outside every range the literature reports for its zone,
        which in this domain is the normal appearance of a real defect —
        the MODIS ET error looked exactly like this and passed every
        test in the suite. Treating warnings as passing would rebuild
        the failure mode this module exists to catch.
        """
        return any(f.is_failure for f in self.findings)

    def summary(self) -> str:
        """One line, suitable for a log record or a CI failure message."""
        if not self.findings:
            return f"{self.subject}: {self.checks_run} checks passed, {self.checks_skipped} skipped"
        return (
            f"{self.subject}: {len(self.errors)} error(s), {len(self.warnings)} warning(s) "
            f"from {self.checks_run} checks ({self.checks_skipped} skipped)"
        )
