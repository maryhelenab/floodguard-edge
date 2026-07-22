"""Tests for MQTT telemetry topic parsing and validation."""

import pytest

from fog_app.mqtt.topic_parser import (
    InvalidTelemetryTopicError,
    parse_telemetry_topic,
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