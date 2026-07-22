"""Tests for independent zone state and rolling sensor windows."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from fog_app.processing.zone_state import ZoneState
from shared.telemetry import SensorType, TelemetryMessage


SENSOR_UNITS: dict[SensorType, str] = {
    "rainfall": "mm/h",
    "water_level": "cm",
    "flow_rate": "L/s",
    "soil_saturation": "%",
    "drain_blockage": "%",
}


def make_telemetry(
    *,
    zone_id: str,
    sensor_type: SensorType,
    value: float,
    timestamp: datetime,
    sequence: int,
) -> TelemetryMessage:
    """Create deterministic telemetry for zone-state tests."""

    return TelemetryMessage(
        event_id=uuid4(),
        device_id=f"{zone_id}-{sensor_type}-01",
        zone_id=zone_id,
        sensor_type=sensor_type,
        value=value,
        unit=SENSOR_UNITS[sensor_type],
        sequence=sequence,
        timestamp=timestamp,
    )


def test_adds_samples_and_calculates_statistics() -> None:
    """Expose latest, average, minimum, maximum, and sample count."""

    state = ZoneState(
        zone_id="dublin-zone-01",
        rolling_window_seconds=60,
    )

    start = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)

    state.add_telemetry(
        make_telemetry(
            zone_id="dublin-zone-01",
            sensor_type="water_level",
            value=10.0,
            timestamp=start,
            sequence=1,
        )
    )
    state.add_telemetry(
        make_telemetry(
            zone_id="dublin-zone-01",
            sensor_type="water_level",
            value=20.0,
            timestamp=start + timedelta(seconds=30),
            sequence=2,
        )
    )

    statistics = state.statistics_for("water_level")

    assert statistics is not None
    assert statistics.latest_value == 20.0
    assert statistics.average_value == 15.0
    assert statistics.minimum_value == 10.0
    assert statistics.maximum_value == 20.0
    assert statistics.sample_count == 2
    assert state.accepted_readings == 2


def test_removes_samples_older_than_time_window() -> None:
    """Remove readings older than the configured duration."""

    state = ZoneState(
        zone_id="dublin-zone-01",
        rolling_window_seconds=60,
    )

    start = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)

    for sequence, seconds, value in [
        (1, 0, 10.0),
        (2, 30, 20.0),
        (3, 61, 30.0),
    ]:
        state.add_telemetry(
            make_telemetry(
                zone_id="dublin-zone-01",
                sensor_type="water_level",
                value=value,
                timestamp=start + timedelta(seconds=seconds),
                sequence=sequence,
            )
        )

    statistics = state.statistics_for("water_level")

    assert statistics is not None
    assert statistics.sample_count == 2
    assert statistics.minimum_value == 20.0
    assert statistics.maximum_value == 30.0


def test_keeps_zone_states_independent() -> None:
    """Prevent telemetry from different zones from sharing state."""

    timestamp = datetime(
        2026,
        7,
        23,
        12,
        0,
        tzinfo=timezone.utc,
    )

    zone_one = ZoneState("dublin-zone-01", 60)
    zone_two = ZoneState("dublin-zone-02", 60)

    zone_one.add_telemetry(
        make_telemetry(
            zone_id="dublin-zone-01",
            sensor_type="rainfall",
            value=10.0,
            timestamp=timestamp,
            sequence=1,
        )
    )
    zone_two.add_telemetry(
        make_telemetry(
            zone_id="dublin-zone-02",
            sensor_type="rainfall",
            value=40.0,
            timestamp=timestamp,
            sequence=1,
        )
    )

    assert zone_one.latest_readings["rainfall"].value == 10.0
    assert zone_two.latest_readings["rainfall"].value == 40.0
    assert zone_one.accepted_readings == 1
    assert zone_two.accepted_readings == 1


def test_keeps_sensor_windows_independent() -> None:
    """Maintain a separate rolling window for each sensor type."""

    state = ZoneState("dublin-zone-01", 60)
    timestamp = datetime(
        2026,
        7,
        23,
        12,
        0,
        tzinfo=timezone.utc,
    )

    state.add_telemetry(
        make_telemetry(
            zone_id="dublin-zone-01",
            sensor_type="rainfall",
            value=15.0,
            timestamp=timestamp,
            sequence=1,
        )
    )
    state.add_telemetry(
        make_telemetry(
            zone_id="dublin-zone-01",
            sensor_type="water_level",
            value=25.0,
            timestamp=timestamp,
            sequence=1,
        )
    )

    assert len(state.window_for("rainfall")) == 1
    assert len(state.window_for("water_level")) == 1
    assert len(state.window_for("flow_rate")) == 0


@pytest.mark.parametrize(
    ("first_value", "last_value", "expected_rate"),
    [
        (10.0, 20.0, 5.0),
        (10.0, 10.0, 0.0),
        (20.0, 10.0, -5.0),
    ],
)
def test_calculates_water_level_rate_of_rise(
    first_value: float,
    last_value: float,
    expected_rate: float,
) -> None:
    """Calculate rising, stable, and falling water-level rates."""

    state = ZoneState("dublin-zone-01", 180)
    start = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)

    state.add_telemetry(
        make_telemetry(
            zone_id="dublin-zone-01",
            sensor_type="water_level",
            value=first_value,
            timestamp=start,
            sequence=1,
        )
    )
    state.add_telemetry(
        make_telemetry(
            zone_id="dublin-zone-01",
            sensor_type="water_level",
            value=last_value,
            timestamp=start + timedelta(minutes=2),
            sequence=2,
        )
    )

    assert state.water_level_rate_of_rise() == pytest.approx(
        expected_rate
    )


def test_returns_zero_with_too_few_water_level_samples() -> None:
    """Return zero before enough water-level samples exist."""

    state = ZoneState("dublin-zone-01", 60)
    timestamp = datetime(
        2026,
        7,
        23,
        12,
        0,
        tzinfo=timezone.utc,
    )

    state.add_telemetry(
        make_telemetry(
            zone_id="dublin-zone-01",
            sensor_type="water_level",
            value=20.0,
            timestamp=timestamp,
            sequence=1,
        )
    )

    assert state.water_level_rate_of_rise() == 0.0


def test_handles_zero_elapsed_time_safely() -> None:
    """Return zero when two readings contain the same timestamp."""

    state = ZoneState("dublin-zone-01", 60)
    timestamp = datetime(
        2026,
        7,
        23,
        12,
        0,
        tzinfo=timezone.utc,
    )

    for sequence, value in [(1, 20.0), (2, 30.0)]:
        state.add_telemetry(
            make_telemetry(
                zone_id="dublin-zone-01",
                sensor_type="water_level",
                value=value,
                timestamp=timestamp,
                sequence=sequence,
            )
        )

    assert state.water_level_rate_of_rise() == 0.0


def test_reports_missing_sensors_during_warm_up() -> None:
    """Remain initialising until every required sensor is available."""

    state = ZoneState("dublin-zone-01", 60)
    timestamp = datetime(
        2026,
        7,
        23,
        12,
        0,
        tzinfo=timezone.utc,
    )

    for sequence, sensor_type in enumerate(
        [
            "rainfall",
            "water_level",
            "flow_rate",
            "soil_saturation",
        ],
        start=1,
    ):
        state.add_telemetry(
            make_telemetry(
                zone_id="dublin-zone-01",
                sensor_type=sensor_type,
                value=10.0,
                timestamp=timestamp,
                sequence=sequence,
            )
        )

    assert state.is_initialising() is True
    assert state.missing_sensor_types() == ("drain_blockage",)

    state.add_telemetry(
        make_telemetry(
            zone_id="dublin-zone-01",
            sensor_type="drain_blockage",
            value=10.0,
            timestamp=timestamp,
            sequence=5,
        )
    )

    assert state.is_initialising() is False
    assert state.missing_sensor_types() == ()