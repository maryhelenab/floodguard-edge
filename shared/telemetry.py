"""Shared telemetry models for FloodGuard Edge."""
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4
from pydantic import BaseModel, Field

SensorType = Literal[
    "rainfall",
    "water_level",
    "flow_rate",
    "soil_saturation",
    "drain_blockage"
]

class TelemetryMessage(BaseModel):
    """Telemetry message model for FloodGuard Edge device."""
    event_id: UUID = Field(default_factory=uuid4, description="Unique identifier for the telemetry event.")
    device_id: str = Field(min_length=1, description="Unique identifier for the device sending the telemetry message.")
    zone_id: str = Field(min_length=1, description="Identifier for the zone where the sensor is located.")
    sensor_type: SensorType = Field(..., description="Type of the sensor.")
    value: float = Field(ge=0, description="Value of the sensor reading.")
    unit: str = Field(min_length=1, description="Unit of measurement for the sensor value.")
    sequence: int = Field(ge=1, description="Sequence number of the telemetry message.")
    timestamp: datetime = Field(..., description="Timestamp when the telemetry message was generated.")