"""Shared telemetry data contract used by the sensor and fog layers.

Keeping this model in ``shared`` ensures that every component expects the
same field names, data types, and validation rules.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# Only these sensor names are accepted by the complete FloodGuard pipeline.
SensorType = Literal[
    "rainfall",
    "water_level",
    "flow_rate",
    "soil_saturation",
    "drain_blockage",
]


class TelemetryMessage(BaseModel):
    """One validated reading published by a simulated IoT sensor."""

    # A UUID lets the fog node detect the same message if MQTT delivers it again.
    event_id: UUID = Field(
        default_factory=uuid4,
        description="Unique identifier for the telemetry event.",
    )

    # The device and zone fields identify where the reading came from.
    device_id: str = Field(
        min_length=1,
        description="Unique identifier for the device sending the telemetry message.",
    )
    zone_id: str = Field(
        min_length=1,
        description="Identifier for the zone where the sensor is located.",
    )
    sensor_type: SensorType = Field(
        description="Type of the sensor.",
    )

    # Sensor values cannot be negative in the current project model.
    value: float = Field(
        ge=0,
        description="Value of the sensor reading.",
    )
    unit: str = Field(
        min_length=1,
        description="Unit of measurement for the sensor value.",
    )

    # Sequence numbers help reject old messages arriving after newer ones.
    sequence: int = Field(
        ge=1,
        description="Sequence number of the telemetry message.",
    )
    timestamp: datetime = Field(
        description="Timestamp when the telemetry message was generated.",
    )
