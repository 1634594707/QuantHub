from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

CONTRACT_VERSION = "1.0.0"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class QualityIssue(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    severity: Severity
    field: str | None = None
    message: str
    source_refs: tuple[str, ...] = ()


class QualityReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    checked_at: datetime
    issues: tuple[QualityIssue, ...]

    @property
    def passed(self) -> bool:
        return all(issue.severity is not Severity.ERROR for issue in self.issues)


def check_missing(record: dict[str, Any], required: Iterable[str]) -> tuple[QualityIssue, ...]:
    return tuple(
        QualityIssue(
            code="missing_field",
            severity=Severity.ERROR,
            field=field,
            message=f"required field {field} is missing",
        )
        for field in required
        if record.get(field) is None
    )


def check_temporal_order(
    event_time: datetime, available_at: datetime, fetched_at: datetime
) -> tuple[QualityIssue, ...]:
    issues: list[QualityIssue] = []
    if any(value.tzinfo is None for value in (event_time, available_at, fetched_at)):
        issues.append(
            QualityIssue(
                code="naive_timestamp",
                severity=Severity.ERROR,
                message="all timestamps must be timezone-aware",
            )
        )
        return tuple(issues)
    if available_at < event_time:
        issues.append(
            QualityIssue(
                code="future_leakage",
                severity=Severity.ERROR,
                message="data became available before its event time",
            )
        )
    if fetched_at < available_at:
        issues.append(
            QualityIssue(
                code="invalid_fetch_time",
                severity=Severity.ERROR,
                message="data was fetched before it became available",
            )
        )
    return tuple(issues)


def check_staleness(
    available_at: datetime, checked_at: datetime, maximum_age: timedelta
) -> tuple[QualityIssue, ...]:
    if checked_at - available_at <= maximum_age:
        return ()
    return (
        QualityIssue(
            code="stale_data",
            severity=Severity.WARNING,
            message=f"data is older than {maximum_age}",
        ),
    )


def check_conflicts(values_by_source: dict[str, Any]) -> tuple[QualityIssue, ...]:
    distinct = {repr(value) for value in values_by_source.values() if value is not None}
    if len(distinct) <= 1:
        return ()
    return (
        QualityIssue(
            code="source_conflict",
            severity=Severity.WARNING,
            message="sources disagree; all source values were preserved",
            source_refs=tuple(sorted(values_by_source)),
        ),
    )
