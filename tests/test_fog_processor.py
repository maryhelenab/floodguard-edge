"""Tests for the broker-independent fog processing pipeline."""

import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fog_app.config.settings import load_fog_config
from fog_app.processing.processor import FogProcessor
from shared.telemetry import SensorType, TelemetryMessage


NOW = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)

UNITS: dict[SensorType, str] = {
    "rainfall": "mm/h",
    "water_level": "cm",
    "flow_rate": "L/s",
    "soil_saturation": "%",
    "drain_blockage": "%",
}


def make_message(
    sensor_type: SensorType,
    *,
    value: float = 10.0,
    sequence: int = 1,
    timestamp: datetime = NOW,
    event_id: UUID | None = None,
    zone_id: str = "dublin-zone-01",
) -> TelemetryMessage:
    """Create deterministic telemetry for processor tests."""

    return TelemetryMessage(
        event_id=event_id or uuid4(),
        device_id=f"{zone_id}-{sensor_type}-01",
        zone_id=zone_id,
        sensor_type=sensor_type,
        value=value,
        unit=UNITS[sensor_type],
        sequence=sequence,
        timestamp=timestamp,
    )


def topic_for(
    sensor_type: SensorType,
    zone_id: str = "dublin-zone-01",
) -> str:
    """Create the MQTT telemetry topic for one sensor."""

    return (
        f"city/drainage/{zone_id}/"
        f"{sensor_type}/telemetry"
    )


def test_accepts_valid_message_and_updates_correct_zone() -> None:
    """Accept valid telemetry and update only its configured zone."""

    processor = FogProcessor(load_fog_config())
    telemetry = make_message("rainfall")

    result = processor.process_message(
        topic_for("rainfall"),
        telemetry.model_dump_json(),
        now=NOW,
    )

    assert result.accepted is True
    assert result.status is not None
    assert result.status.risk_level == "INITIALISING"
    assert processor.counters.accepted == 1

    zone_one = processor.zone_states["dublin-zone-01"]
    zone_two = processor.zone_states["dublin-zone-02"]

    assert zone_one.latest_readings["rainfall"].event_id == telemetry.event_id
    assert zone_two.latest_readings == {}


def test_rejects_malformed_json() -> None:
    """Reject malformed JSON without changing zone state."""

    processor = FogProcessor(load_fog_config())

    result = processor.process_message(
        topic_for("rainfall"),
        "{not-valid-json",
        now=NOW,
    )

    assert result.accepted is False
    assert result.rejection_reason == "invalid_json"
    assert processor.counters.invalid_json == 1


def test_rejects_invalid_pydantic_payload() -> None:
    """Reject JSON whose telemetry fields are invalid."""

    processor = FogProcessor(load_fog_config())
    payload = json.loads(
        make_message("rainfall").model_dump_json()
    )
    payload["sequence"] = 0

    result = processor.process_message(
        topic_for("rainfall"),
        json.dumps(payload),
        now=NOW,
    )

    assert result.accepted is False
    assert result.rejection_reason == "validation_failure"


def test_rejects_topic_payload_mismatch() -> None:
    """Reject a payload whose sensor differs from the MQTT topic."""

    processor = FogProcessor(load_fog_config())
    telemetry = make_message("rainfall")

    result = processor.process_message(
        topic_for("water_level"),
        telemetry.model_dump_json(),
        now=NOW,
    )

    assert result.accepted is False
    assert result.rejection_reason == "topic_mismatch"


def test_duplicate_does_not_enter_window_twice() -> None:
    """Ignore a repeated event ID without changing the rolling window."""

    processor = FogProcessor(load_fog_config())
    telemetry = make_message("rainfall")
    payload = telemetry.model_dump_json()

    first_result = processor.process_message(
        topic_for("rainfall"),
        payload,
        now=NOW,
    )
    second_result = processor.process_message(
        topic_for("rainfall"),
        payload,
        now=NOW,
    )

    window = processor.zone_states[
        "dublin-zone-01"
    ].window_for("rainfall")

    assert first_result.accepted is True
    assert second_result.accepted is False
    assert second_result.rejection_reason == "duplicate"
    assert len(window) == 1


def test_rejects_stale_message() -> None:
    """Reject telemetry older than the configured maximum age."""

    processor = FogProcessor(load_fog_config())
    telemetry = make_message(
        "rainfall",
        timestamp=NOW - timedelta(seconds=61),
    )

    result = processor.process_message(
        topic_for("rainfall"),
        telemetry.model_dump_json(),
        now=NOW,
    )

    assert result.accepted is False
    assert result.rejection_reason == "stale_message"


def test_rejects_out_of_order_sequence() -> None:
    """Reject a lower sequence from the same device."""

    processor = FogProcessor(load_fog_config())

    first_message = make_message("rainfall", sequence=2)
    second_message = make_message("rainfall", sequence=1)

    first_result = processor.process_message(
        topic_for("rainfall"),
        first_message.model_dump_json(),
        now=NOW,
    )
    second_result = processor.process_message(
        topic_for("rainfall"),
        second_message.model_dump_json(),
        now=NOW,
    )

    assert first_result.accepted is True
    assert second_result.accepted is False
    assert second_result.rejection_reason == "out_of_order"


def test_final_sensor_completes_warm_up_and_calculates_risk() -> None:
    """Calculate a normal risk result after all sensors arrive."""

    processor = FogProcessor(load_fog_config())

    values: dict[SensorType, float] = {
        "rainfall": 10.0,
        "water_level": 10.0,
        "flow_rate": 3.0,
        "soil_saturation": 20.0,
        "drain_blockage": 10.0,
    }

    final_result = None

    for sensor_type, value in values.items():
        final_result = processor.process_message(
            topic_for(sensor_type),
            make_message(
                sensor_type,
                value=value,
            ).model_dump_json(),
            now=NOW,
        )

    assert final_result is not None
    assert final_result.accepted is True
    assert final_result.status is not None
    assert final_result.status.risk_level == "NORMAL"
    assert final_result.status.risk_score is not None
    assert final_result.alert is None
    assert processor.counters.risk_calculations == 1


def test_critical_conditions_generate_alert() -> None:
    """Create an immediate alert when completed inputs are critical."""

    processor = FogProcessor(load_fog_config())

    values: dict[SensorType, float] = {
        "rainfall": 70.0,
        "water_level": 80.0,
        "flow_rate": 25.0,
        "soil_saturation": 90.0,
        "drain_blockage": 80.0,
    }

    final_result = None

    for sensor_type, value in values.items():
        final_result = processor.process_message(
            topic_for(sensor_type),
            make_message(
                sensor_type,
                value=value,
            ).model_dump_json(),
            now=NOW,
        )

    assert final_result is not None
    assert final_result.status is not None
    assert final_result.status.risk_level == "CRITICAL"
    assert final_result.alert is not None
    assert final_result.alert.severity == "CRITICAL"
    assert processor.counters.alerts_created == 1