"""Deterministic status and alert publication policies."""

from datetime import datetime, timezone
from typing import cast

from fog_app.models import (
    AlertSeverity,
    StatusRiskLevel,
)


RISK_LEVEL_ORDER: dict[StatusRiskLevel, int] = {
    "INITIALISING": -1,
    "NORMAL": 0,
    "WATCH": 1,
    "WARNING": 2,
    "HIGH": 3,
    "CRITICAL": 4,
}

ALERT_LEVEL_ORDER: dict[AlertSeverity, int] = {
    "WARNING": 1,
    "HIGH": 2,
    "CRITICAL": 3,
}


def _elapsed_seconds(
    *,
    now: datetime,
    previous_time: datetime,
) -> float:
    """Calculate elapsed seconds using timezone-aware timestamps."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Current time must include timezone information.")

    if (
        previous_time.tzinfo is None
        or previous_time.utcoffset() is None
    ):
        raise ValueError(
            "Previous publication time must include timezone information."
        )

    now_utc = now.astimezone(timezone.utc)
    previous_utc = previous_time.astimezone(timezone.utc)

    return (now_utc - previous_utc).total_seconds()


def should_publish_status(
    *,
    previous_level: StatusRiskLevel | None,
    current_level: StatusRiskLevel,
    last_publication_time: datetime | None,
    now: datetime,
    interval_seconds: float,
    warm_up_completed: bool = False,
    force: bool = False,
) -> bool:
    """Return whether a processed zone status should be published."""

    if interval_seconds < 0:
        raise ValueError(
            "Status publication interval cannot be negative."
        )

    if force:
        return True

    if warm_up_completed:
        return True

    if last_publication_time is None:
        return True

    if previous_level != current_level:
        return True

    elapsed_seconds = _elapsed_seconds(
        now=now,
        previous_time=last_publication_time,
    )

    return elapsed_seconds >= interval_seconds


def should_publish_alert(
    *,
    previous_level: StatusRiskLevel | None,
    current_level: StatusRiskLevel,
    last_alert_severity: AlertSeverity | None,
    last_alert_publication_time: datetime | None,
    now: datetime,
    cooldown_seconds: float,
) -> bool:
    """Return whether the current transition should create an alert."""

    if cooldown_seconds < 0:
        raise ValueError("Alert cooldown cannot be negative.")

    if current_level not in ALERT_LEVEL_ORDER:
        return False

    current_severity = cast(AlertSeverity, current_level)
    current_risk_rank = RISK_LEVEL_ORDER[current_level]

    if previous_level is None:
        return True

    previous_risk_rank = RISK_LEVEL_ORDER[previous_level]

    # Any escalation publishes immediately, even during cooldown.
    if current_risk_rank > previous_risk_rank:
        return True

    # De-escalation updates status but does not create an emergency alert.
    if current_risk_rank < previous_risk_rank:
        return False

    if (
        last_alert_severity is None
        or last_alert_publication_time is None
    ):
        return True

    current_alert_rank = ALERT_LEVEL_ORDER[current_severity]
    previous_alert_rank = ALERT_LEVEL_ORDER[last_alert_severity]

    if current_alert_rank > previous_alert_rank:
        return True

    if current_alert_rank < previous_alert_rank:
        return False

    elapsed_seconds = _elapsed_seconds(
        now=now,
        previous_time=last_alert_publication_time,
    )

    return elapsed_seconds >= cooldown_seconds