"""Tests for fog output models and publication policies."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from fog_app.models import (
    DerivedMetrics,
    FogAlert,
    FogStatus,
    SampleCounts,
    SensorSnapshot,
)
from fog_app.processing.publication_policy import (
    should_publish_alert,
    should_publish_status,
)


NOW = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)


def make_status(
    *,
    risk_level: str = "WARNING",
    risk_score: float | None = 60.0,
) -> FogStatus:
    """Create a valid deterministic fog status."""

    return FogStatus(
        fog_node_id="fog-node-dublin-01",
        zone_id="dublin-zone-01",
        risk_level=risk_level,
        risk_score=risk_score,
        computed_at=NOW,
        window_seconds=60,
        sensor_snapshot=SensorSnapshot(
            rainfall=40.0,
            water_level=50.0,
            flow_rate=15.0,
            soil_saturation=70.0,
            drain_blockage=60.0,
        ),
        derived_metrics=DerivedMetrics(
            water_rise_cm_min=4.0,
            flow_utilisation_percent=50.0,
            drainage_stress_score=50.0,
        ),
        sample_counts=SampleCounts(
            rainfall=5,
            water_level=5,
            flow_rate=5,
            soil_saturation=5,
            drain_blockage=5,
        ),
        reasons=["Elevated combined flood-risk conditions."],
        source_event_ids=[uuid4()],
    )


def test_status_model_serialises_complete_payload() -> None:
    """Serialise a valid processed status as JSON."""

    status = make_status()
    payload = status.model_dump_json()

    assert '"risk_level":"WARNING"' in payload
    assert '"risk_score":60.0' in payload
    assert '"water_level":50.0' in payload


def test_initialising_status_accepts_missing_risk_score() -> None:
    """Allow warm-up status before a final risk score exists."""

    status = FogStatus(
        fog_node_id="fog-node-dublin-01",
        zone_id="dublin-zone-01",
        risk_level="INITIALISING",
        risk_score=None,
        computed_at=NOW,
        window_seconds=60,
        sensor_snapshot=SensorSnapshot(rainfall=10.0),
        derived_metrics=DerivedMetrics(
            water_rise_cm_min=0.0,
            flow_utilisation_percent=0.0,
            drainage_stress_score=0.0,
        ),
        sample_counts=SampleCounts(rainfall=1),
        reasons=["Waiting for required sensor readings."],
        missing_sensor_types=[
            "water_level",
            "flow_rate",
            "soil_saturation",
            "drain_blockage",
        ],
        source_event_ids=[uuid4()],
    )

    assert status.risk_level == "INITIALISING"
    assert status.risk_score is None


def test_calculated_status_requires_risk_score() -> None:
    """Reject a completed risk status without its numeric score."""

    with pytest.raises(
        ValidationError,
        match="must contain a risk score",
    ):
        make_status(
            risk_level="WARNING",
            risk_score=None,
        )


def test_initialising_status_rejects_final_score() -> None:
    """Reject a final risk score during zone warm-up."""

    with pytest.raises(
        ValidationError,
        match="cannot contain a final risk score",
    ):
        make_status(
            risk_level="INITIALISING",
            risk_score=20.0,
        )


def test_alert_model_serialises_complete_payload() -> None:
    """Serialise a validated critical-alert payload."""

    alert = FogAlert(
        fog_node_id="fog-node-dublin-01",
        zone_id="dublin-zone-01",
        severity="CRITICAL",
        risk_score=91.2,
        triggered_at=NOW,
        message="Critical urban flooding risk detected.",
        reasons=[
            "Water level reached the critical threshold.",
        ],
        recommended_action=(
            "Inspect the drainage zone immediately and activate "
            "the local emergency response procedure."
        ),
        source_status_event_id=uuid4(),
    )

    assert alert.severity == "CRITICAL"
    assert '"severity":"CRITICAL"' in alert.model_dump_json()


@pytest.mark.parametrize(
    (
        "previous_level",
        "current_level",
        "last_publication_time",
        "warm_up_completed",
        "force",
        "expected",
    ),
    [
        (None, "INITIALISING", None, False, False, True),
        ("NORMAL", "WATCH", NOW, False, False, True),
        ("NORMAL", "NORMAL", NOW, True, False, True),
        ("NORMAL", "NORMAL", NOW, False, True, True),
        ("NORMAL", "NORMAL", NOW, False, False, False),
    ],
)
def test_status_publication_conditions(
    previous_level,
    current_level,
    last_publication_time,
    warm_up_completed,
    force,
    expected,
) -> None:
    """Publish status for initial, changed, forced, or warm-up events."""

    assert (
        should_publish_status(
            previous_level=previous_level,
            current_level=current_level,
            last_publication_time=last_publication_time,
            now=NOW,
            interval_seconds=5,
            warm_up_completed=warm_up_completed,
            force=force,
        )
        is expected
    )


def test_status_publishes_after_interval() -> None:
    """Publish an unchanged status after the configured interval."""

    assert (
        should_publish_status(
            previous_level="NORMAL",
            current_level="NORMAL",
            last_publication_time=NOW,
            now=NOW + timedelta(seconds=5),
            interval_seconds=5,
        )
        is True
    )


@pytest.mark.parametrize(
    ("previous_level", "current_level"),
    [
        ("NORMAL", "WARNING"),
        ("WARNING", "HIGH"),
        ("HIGH", "CRITICAL"),
    ],
)
def test_alerts_publish_on_escalation(
    previous_level,
    current_level,
) -> None:
    """Publish immediately whenever alert severity escalates."""

    assert (
        should_publish_alert(
            previous_level=previous_level,
            current_level=current_level,
            last_alert_severity="WARNING",
            last_alert_publication_time=NOW,
            now=NOW + timedelta(seconds=1),
            cooldown_seconds=30,
        )
        is True
    )


def test_repeated_alert_inside_cooldown_is_suppressed() -> None:
    """Suppress repeated identical alert severity during cooldown."""

    assert (
        should_publish_alert(
            previous_level="WARNING",
            current_level="WARNING",
            last_alert_severity="WARNING",
            last_alert_publication_time=NOW,
            now=NOW + timedelta(seconds=10),
            cooldown_seconds=30,
        )
        is False
    )


def test_repeated_alert_after_cooldown_is_allowed() -> None:
    """Allow a repeated alert after the cooldown has elapsed."""

    assert (
        should_publish_alert(
            previous_level="WARNING",
            current_level="WARNING",
            last_alert_severity="WARNING",
            last_alert_publication_time=NOW,
            now=NOW + timedelta(seconds=30),
            cooldown_seconds=30,
        )
        is True
    )


def test_alert_escalation_bypasses_cooldown() -> None:
    """Publish a HIGH alert immediately after a recent WARNING alert."""

    assert (
        should_publish_alert(
            previous_level="WARNING",
            current_level="HIGH",
            last_alert_severity="WARNING",
            last_alert_publication_time=NOW,
            now=NOW + timedelta(seconds=1),
            cooldown_seconds=30,
        )
        is True
    )


@pytest.mark.parametrize(
    ("previous_level", "current_level"),
    [
        ("CRITICAL", "HIGH"),
        ("HIGH", "WARNING"),
        ("WARNING", "WATCH"),
        ("WARNING", "NORMAL"),
    ],
)
def test_deescalation_does_not_publish_emergency_alert(
    previous_level,
    current_level,
) -> None:
    """Update status without producing a duplicate emergency alert."""

    assert (
        should_publish_alert(
            previous_level=previous_level,
            current_level=current_level,
            last_alert_severity="CRITICAL",
            last_alert_publication_time=NOW,
            now=NOW + timedelta(seconds=60),
            cooldown_seconds=30,
        )
        is False
    )