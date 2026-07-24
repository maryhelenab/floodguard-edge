"""Validate fog MQTT outputs before they enter the AWS backend."""

import json
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from fog_app.models import FogAlert, FogStatus


EventType = Literal["status", "alert"]


def read_fog_topic(topic: str) -> tuple[str, EventType]:
    """Extract the zone and event type from a fog output topic.
    Expected format: ``city/drainage/{zone_id}/fog/{status|alert}``.
    """

    parts = topic.split("/")

    # Validate every fixed topic segment so unexpected MQTT messages are ignored.
    valid_topic = (
        len(parts) == 5
        and parts[0] == "city"
        and parts[1] == "drainage"
        and bool(parts[2])
        and parts[3] == "fog"
        and parts[4] in {"status", "alert"}
    )

    if not valid_topic:
        raise ValueError(f"Invalid fog MQTT topic: {topic}")

    zone_id = parts[2]
    event_type = parts[4]

    return zone_id, event_type


class CloudEventEnvelope(BaseModel):
    """Stable message format sent from the cloud bridge to Amazon SQS."""

    event_type: EventType
    mqtt_topic: str

    # Record when the bridge received the event, independently of sensor time.
    received_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    # Pydantic selects and validates either the status or alert structure.
    payload: FogStatus | FogAlert

    @classmethod
    def from_mqtt(
        cls,
        topic: str,
        payload: bytes | str,
    ) -> "CloudEventEnvelope":
        """Convert one raw MQTT message into a validated cloud event."""

        zone_id, event_type = read_fog_topic(topic)

        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")

        # Decode JSON before asking Pydantic to validate individual fields.
        try:
            payload_data = json.loads(payload)
        except (json.JSONDecodeError, TypeError) as error:
            raise ValueError(
                "The MQTT payload is not valid JSON."
            ) from error

        payload_model = FogStatus if event_type == "status" else FogAlert
        validated_payload = payload_model.model_validate(payload_data)

        # Prevent a message from being stored under the wrong zone partition.
        if validated_payload.zone_id != zone_id:
            raise ValueError(
                "The zone in the topic does not match "
                "the zone in the payload."
            )

        return cls(
            event_type=event_type,
            mqtt_topic=topic,
            payload=validated_payload,
        )

    @property
    def zone_id(self) -> str:
        """Return the zone identifier without checking the payload type."""

        return self.payload.zone_id

    @property
    def event_id(self) -> str:
        """Return the original status or alert identifier as text."""

        if isinstance(self.payload, FogStatus):
            return str(self.payload.event_id)

        return str(self.payload.alert_id)

    @property
    def event_time(self) -> datetime:
        """Return the time when the fog node created the status or alert."""

        if isinstance(self.payload, FogStatus):
            return self.payload.computed_at

        return self.payload.triggered_at
