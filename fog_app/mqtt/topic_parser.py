"""Parse MQTT telemetry topics and verify that topic and payload agree."""

from dataclasses import dataclass
from typing import cast, get_args
from shared.telemetry import SensorType, TelemetryMessage

# Reuse the day 1 SensorType definition so the topic parser cannot
# Silently introduce sensor names that are incompatible with the rest of the system.
VALID_SENSOR_TYPES = frozenset(get_args(SensorType))

class InvalidTelemetryTopicError(ValueError):
    """Raised when a telemetry topic is invalid."""

class TelemetryTopicMismatchError(ValueError):
    """Raised when the MQTT topic does not match the telemetry payload."""

@dataclass(frozen=True, slots=True)
class ParsedTelemetryTopic:
    """Structured values extracted from a valid telemetry topic."""

    zone_id: str
    sensor_type: SensorType

# Expected format: city/drainage/{zone}/{sensor}/{device}/telemetry
def parse_telemetry_topic(topic: str) -> ParsedTelemetryTopic:
    """Parse a telemetry topic into its structured components.

    Args:
        topic: The MQTT topic to parse.

    Returns:
        A ParsedTelemetryTopic object containing the zone ID and sensor type.

    Raises:
        InvalidTelemetryTopicError: If the topic is invalid.
    """
    # Splitting once makes every segment easy to validate explicitly.
    parts = topic.split("/")

    if len(parts) != 5:
        raise InvalidTelemetryTopicError(
            f"Telemetry topic must contain five segments: {topic!r}"
        )

    city_segment, drainage_segment, zone_id, sensor_type_str, suffix = parts

    if city_segment != "city" or drainage_segment != "drainage":
        raise InvalidTelemetryTopicError(
            f"Telemetry topic must start with 'city/drainage': {topic!r}"
        )

    if suffix != "telemetry":
        raise InvalidTelemetryTopicError(
            f"Telemetry topic must end with 'telemetry': {topic!r}"
        )

    if not zone_id.strip():
        raise InvalidTelemetryTopicError(
            f"Telemetry topic must contain a non-empty zone ID: {topic!r}"
        )

    if sensor_type_str not in VALID_SENSOR_TYPES:
        raise InvalidTelemetryTopicError(
            f"Unsupported sensor type in telemetry topic: {sensor_type_str!r}"
        )
    
    return ParsedTelemetryTopic(
        zone_id=zone_id,
        sensor_type=cast(SensorType, sensor_type_str),
    )

def validate_topic_matches_payload(
        parsed_topic: ParsedTelemetryTopic,
        telemetry: TelemetryMessage,
) -> None:
    """Ensure the telemetry payload matches its MQTT topic."""
    # Mismatches could route a reading into the wrong zone or sensor window.
    if parsed_topic.zone_id != telemetry.zone_id:
        raise TelemetryTopicMismatchError(
            "Telemetry zone does not match the MQTT topic: "
            f"topic={parsed_topic.zone_id!r}, payload={telemetry.zone_id!r}"
        )

    if parsed_topic.sensor_type != telemetry.sensor_type:
        raise TelemetryTopicMismatchError(
            "Telemetry sensor type does not match the MQTT topic: "
            f"topic={parsed_topic.sensor_type!r}, "
            f"payload={telemetry.sensor_type!r}"
        )