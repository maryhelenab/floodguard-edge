"""Tests for MQTT telemetry topic parsing and validation."""
from datetime import datetime, timezone
from uuid import uuid4
from shared.telemetry import TelemetryMessage

import pytest

from fog_app.mqtt.topic_parser import (
    InvalidTelemetryTopicError,
    parse_telemetry_topic,
    validate_topic_matches_payload,
    TelemetryTopicMismatchError,
)


def test_parse_valid_telemetry_topic() -> None:
    """Extract the zone and sensor type from a valid telemetry topic."""

    parsed_topic = parse_telemetry_topic(
        "city/drainage/dublin-zone-01/water_level/telemetry"
    )

    assert parsed_topic.zone_id == "dublin-zone-01"
    assert parsed_topic.sensor_type == "water_level"


@pytest.mark.parametrize(
    'invalid_topic',
    [
        "city/drainage/dublin-zone-01/water_level",  # Missing suffix
        "building/drainage/dublin-zone-01/water_level/telemetry",  # Invalid prefix
        "city/drainage/dublin-zone-01/water_level/status",  # Invalid suffix
        "city/drainage//water_level/telemetry",  # Empty zone ID
        "city/drainage/dublin-zone-01/temperature/telemetry",  # Invalid sensor type
    ]
)
def test_reject_invalid_telemetry_topics(
    invalid_topic: str,
) -> None:
    """Reject telemetry topics that do not follow the expected format."""

    with pytest.raises(InvalidTelemetryTopicError):
        parse_telemetry_topic(invalid_topic)

def test_accept_matching_topic_and_payload() -> None:
    """Accept a telemetry payload that matches its MQTT topic."""

    parsed_topic = parse_telemetry_topic(
        "city/drainage/dublin-zone-01/water_level/telemetry"
    )

    telemetry = TelemetryMessage(
        event_id=uuid4(),
        device_id="dublin-zone-01-water_level-01",
        zone_id="dublin-zone-01",
        sensor_type="water_level",
        value=35.0,
        unit="cm",
        sequence=1,
        timestamp=datetime.now(timezone.utc),
    )

    validate_topic_matches_payload(parsed_topic, telemetry)

def test_reject_payload_with_different_zone() -> None:
    """Reject a telemetry payload that has a different zone than its MQTT topic."""

    parsed_topic = parse_telemetry_topic(
        "city/drainage/dublin-zone-01/water_level/telemetry"
    )

    telemetry = TelemetryMessage(
        event_id=uuid4(),
        device_id="dublin-zone-02-water_level-01",
        zone_id="dublin-zone-02",  # Different zone
        sensor_type="water_level",
        value=35.0,
        unit="cm",
        sequence=1,
        timestamp=datetime.now(timezone.utc),
    )

    with pytest.raises(
        TelemetryTopicMismatchError,
        match="Telemetry zone does not match the MQTT topic",
    ):
        validate_topic_matches_payload(parsed_topic, telemetry)

def test_reject_payload_with_different_sensor_type() -> None:
    """Reject a telemetry payload that has a different sensor type than its MQTT topic."""

    parsed_topic = parse_telemetry_topic(
        "city/drainage/dublin-zone-01/water_level/telemetry"
    )

    telemetry = TelemetryMessage(
        event_id=uuid4(),
        device_id="dublin-zone-01-rainfall-01",
        zone_id="dublin-zone-01",
        sensor_type="rainfall",  # Different sensor type
        value=12.0,
        unit="mm",
        sequence=1,
        timestamp=datetime.now(timezone.utc),
    )

    with pytest.raises(
        TelemetryTopicMismatchError,
        match="Telemetry sensor type does not match the MQTT topic",
    ):
        validate_topic_matches_payload(parsed_topic, telemetry)