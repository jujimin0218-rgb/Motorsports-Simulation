"""Generic validation reporting.

Project rule 39 asks for automatic validation of *every* system, not just the
track: aero must produce more downforce at higher speed, more power must give
more acceleration, more grip must give more cornering.  Those checks live with
the systems they test, but they all report the same way, so the machinery is
here.

A check is a function returning a list of :class:`ValidationIssue`.  A suite is
a list of checks.  Adding one is appending a function -- which is what keeps
the suites growing as the engine does, instead of quietly falling behind it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar

from .errors import ValidationError

__all__ = ["Severity", "ValidationIssue", "ValidationReport", "run_checks"]


class Severity(str, Enum):
    """How bad a finding is.

    ``ERROR`` stops the pipeline; ``WARNING`` is a result worth looking at that
    is still physically possible; ``INFO`` records a measured number so the
    report is useful even when nothing is wrong.
    """

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


_ORDER = {Severity.INFO: 0, Severity.WARNING: 1, Severity.ERROR: 2}


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """One finding."""

    check: str
    severity: Severity
    message: str
    distance: float | None = None
    segment_index: int | None = None

    def __str__(self) -> str:
        where = ""
        if self.distance is not None:
            where = f" @ {self.distance:.1f} m"
            if self.segment_index is not None:
                where += f" (segment {self.segment_index})"
        return f"[{self.severity.value.upper():7}] {self.check}{where}: {self.message}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "severity": self.severity.value,
            "message": self.message,
            "distance": self.distance,
            "segment_index": self.segment_index,
        }


@dataclass(frozen=True)
class ValidationReport:
    """The result of running a suite of checks against one subject."""

    subject: str
    issues: tuple[ValidationIssue, ...] = ()

    #: Human-readable label for the report header.
    kind: ClassVar[str] = "Validation"

    #: Exception raised by :meth:`raise_for_errors`.
    error_type: ClassVar[type[Exception]] = ValidationError

    # -- queries -------------------------------------------------------------

    def of_severity(self, severity: Severity) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity is severity)

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return self.of_severity(Severity.ERROR)

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return self.of_severity(Severity.WARNING)

    @property
    def infos(self) -> tuple[ValidationIssue, ...]:
        return self.of_severity(Severity.INFO)

    @property
    def ok(self) -> bool:
        """True when nothing was reported as an error."""
        return not self.errors

    @property
    def clean(self) -> bool:
        """True when there are no errors *and* no warnings."""
        return not self.errors and not self.warnings

    # -- output --------------------------------------------------------------

    def raise_for_errors(self) -> ValidationReport:
        """Raise if any error was reported; return self otherwise."""
        errors = self.errors
        if errors:
            detail = "\n".join(f"  {issue}" for issue in errors)
            raise self.error_type(
                f"{self.subject!r} failed validation:\n{detail}", self
            )
        return self

    def format(self, *, min_severity: Severity = Severity.INFO) -> str:
        threshold = _ORDER[min_severity]
        shown = [i for i in self.issues if _ORDER[i.severity] >= threshold]
        header = (
            f"{self.kind}: {self.subject} -- "
            f"{len(self.errors)} error(s), {len(self.warnings)} warning(s), "
            f"{len(self.infos)} note(s)"
        )
        if not shown:
            return header + "\n  (nothing to report)"
        return header + "\n" + "\n".join(f"  {issue}" for issue in shown)

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "ok": self.ok,
            "clean": self.clean,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "issues": [issue.to_dict() for issue in self.issues],
        }

    def __len__(self) -> int:
        return len(self.issues)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"{type(self).__name__}({self.subject!r}, errors={len(self.errors)}, "
            f"warnings={len(self.warnings)})"
        )


def run_checks(
    subject: str,
    checks: Iterable[Callable[..., list[ValidationIssue]]],
    *args: Any,
    report_type: type[ValidationReport] = ValidationReport,
    **kwargs: Any,
) -> ValidationReport:
    """Run every check in ``checks`` and collect the findings."""
    issues: list[ValidationIssue] = []
    for check in checks:
        issues.extend(check(*args, **kwargs))
    return report_type(subject=subject, issues=tuple(issues))
