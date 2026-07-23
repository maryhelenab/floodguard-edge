"""Tests for minimal SQLite fog-event persistence."""

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fog_app.models import (
    DerivedMetrics,
    FogAlert,
    FogStatus,
    SampleCounts,
    SensorSnapshot,
)
from fog_app.persistence import FogEventStore


NOW = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)


def make_status() -> FogStatus:
    """Create one valid processed status."""

    return FogStatus(
        fog_node_id="fog-node-dublin-01",
        zone_id="dublin-zone-01",
        risk_level="WARNING",
        risk_score=60.0,
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
            rainfall=1,
            water_level=1,
            flow_rate=1,
            soil_saturation=1,
            drain_blockage=1,
        ),
        reasons=["Elevated flood-risk conditions."],
        source_event_ids=[uuid4()],
    )


def make_alert(status: FogStatus) -> FogAlert:
    """Create one valid alert linked to a status."""

    return FogAlert(
        fog_node_id="fog-node-dublin-01",
        zone_id="dublin-zone-01",
        severity="WARNING",
        risk_score=60.0,
        triggered_at=NOW,
        message="Flood-risk warning detected.",
        reasons=["Elevated flood-risk conditions."],
        recommended_action="Inspect the drainage zone.",
        source_status_event_id=status.event_id,
    )


def test_creates_database_and_persists_status(
    tmp_path: Path,
) -> None:
    """Create the database and store one status."""

    database_path = tmp_path / "fog" / "fog_events.db"
    store = FogEventStore(database_path)

    assert database_path.exists()
    assert store.persist_status(make_status()) is True
    assert store.count_statuses() == 1


def test_persists_alert(
    tmp_path: Path,
) -> None:
    """Store one alert linked to a processed status."""

    store = FogEventStore(tmp_path / "fog_events.db")
    status = make_status()
    alert = make_alert(status)

    assert store.persist_alert(alert) is True
    assert store.count_alerts() == 1