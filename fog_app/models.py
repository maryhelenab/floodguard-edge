"""Validated output contracts produced by the FloodGuard fog node.

These models are published to MQTT, stored locally, forwarded to AWS, and
consumed by the dashboard, so stable field names are important.
"""

from typing import Literal
from uuid import UUID, uuid4

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from shared.telemetry import SensorType


StatusRiskLevel = Literal[
    "INITIALISING",
    "NORMAL",
    "WATCH",
    "WARNING",
    "HIGH",
    "CRITICAL",
]

AlertSeverity = Literal[
    "WARNING",
    "HIGH",
    "CRITICAL",
]


# Shared serialisation rules for all fog outputs.
class FogOutputModel(BaseModel):
    """Shared strict configuration for fog-node output messages."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )


# Latest raw measurement from each sensor type.
class SensorSnapshot(FogOutputModel):
    """Latest accepted value for every supported sensor type."""

    rainfall: float | None = Field(default=None, ge=0.0)
    water_level: float | None = Field(default=None, ge=0.0)
    flow_rate: float | None = Field(default=None, ge=0.0)
    soil_saturation: float | None = Field(default=None, ge=0.0)
    drain_blockage: float | None = Field(default=None, ge=0.0)


# Values calculated locally from several raw readings.
class DerivedMetrics(FogOutputModel):
    """Metrics derived locally from accepted telemetry."""

    water_rise_cm_min: float
    flow_utilisation_percent: float = Field(ge=0.0, le=100.0)
    drainage_stress_score: float = Field(ge=0.0, le=100.0)


# Number of readings currently present in each rolling window.
class SampleCounts(FogOutputModel):
    """Number of samples currently stored in each rolling window."""

    rainfall: int = Field(default=0, ge=0)
    water_level: int = Field(default=0, ge=0)
    flow_rate: int = Field(default=0, ge=0)
    soil_saturation: int = Field(default=0, ge=0)
    drain_blockage: int = Field(default=0, ge=0)


# Periodic full state used by the cloud API and dashboard.
class FogStatus(FogOutputModel):
    """Aggregated processing status for one monitored urban zone."""

    event_id: UUID = Field(default_factory=uuid4)
    fog_node_id: str = Field(min_length=1)
    zone_id: str = Field(min_length=1)

    risk_level: StatusRiskLevel
    risk_score: float | None = Field(
        default=None,
        ge=0.0,
        le=100.0,
    )

    computed_at: AwareDatetime
    window_seconds: int = Field(ge=1)

    sensor_snapshot: SensorSnapshot
    derived_metrics: DerivedMetrics
    sample_counts: SampleCounts

    reasons: list[str] = Field(min_length=1)

    missing_sensor_types: list[SensorType] = Field(
        default_factory=list,
    )

    # The processor will apply the smaller configurable limit.
    source_event_ids: list[UUID] = Field(
        default_factory=list,
        max_length=100,
    )

    @model_validator(mode="after")
    def validate_risk_state(self) -> "FogStatus":
        """Keep INITIALISING and calculated-risk statuses unambiguous."""

        if (
            self.risk_level == "INITIALISING"
            and self.risk_score is not None
        ):
            raise ValueError(
                "INITIALISING status cannot contain a final risk score."
            )

        if (
            self.risk_level != "INITIALISING"
            and self.risk_score is None
        ):
            raise ValueError(
                "A calculated risk status must contain a risk score."
            )

        return self


# Event emitted only when a serious condition needs attention.
class FogAlert(FogOutputModel):
    """Immediate flood-risk escalation alert produced by the fog node."""

    alert_id: UUID = Field(default_factory=uuid4)
    fog_node_id: str = Field(min_length=1)
    zone_id: str = Field(min_length=1)

    severity: AlertSeverity
    risk_score: float = Field(ge=0.0, le=100.0)
    triggered_at: AwareDatetime

    message: str = Field(min_length=1)
    reasons: list[str] = Field(min_length=1)
    recommended_action: str = Field(min_length=1)

    source_status_event_id: UUID