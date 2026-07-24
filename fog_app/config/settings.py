"""Load and validate every setting used by the FloodGuard fog node.

Pydantic rejects invalid configuration before the node starts, preventing
runtime errors in MQTT, risk calculation, and persistence.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from shared.telemetry import SensorType


# MQTT connection and topic settings.
class MqttSettings(BaseModel):
    """MQTT settings for the FloodGuard fog node"""

    host: str = Field(min_length=1, description="MQTT broker host")
    port: int = Field(ge= 1, le=65535, description="MQTT broker port")
    keepalive: int = Field(gt=0, description="MQTT keepalive interval in seconds")

    # # QoS 1 provides at-least-once delivery, so the same telemetry
    # event may arrive more than once and must be deduplicated by event_id.
    qos: Literal[0, 1, 2] = Field(default=1, description="MQTT Quality of Service level")

    client_id_prefix: str = Field(min_length=1, description="MQTT client ID prefix")
    telemetry_subscription_topic: str = Field(min_length=1, description="MQTT topic for telemetry subscription")

    status_topic_template: str = Field(min_length=1, description="MQTT topic template for status messages")
    alert_topic_template: str = Field(min_length=1, description="MQTT topic template for alert messages")

    health_topic: str = Field(min_length=1, description="MQTT topic for health messages")
    health_enabled: bool = Field(default=False, description="Whether health messages are enabled")
    retain_outputs: bool = Field(default=False, description="Whether to retain output messages")


# Local validation, rolling-window, and publication settings.
class ProcessingSettings(BaseModel):
    """Processing settings for the FloodGuard fog node"""

    required_sensor_types: list[SensorType] = Field(
        min_length=1,
        description="List of required sensor types for processing"
    )

    rolling_window_seconds: int = Field(
        gt=0,
        description="Duration of the rolling window for processing in seconds"
    )

    # Two timestamped samples are the minimum required to calculate
    # The water-level rate of rise.
    minimum_samples_for_trend: int = Field(
        ge=2,
        description="Minimum number of samples required to determine a trend"
    )

    stale_message_validation_enabled: bool = Field(
        default=True,
        description="Whether to validate messages for staleness"
    )

    maximum_message_age_seconds: int = Field(
        gt=0,
        description="Maximum age of a message in seconds before it is considered stale"
    )

    reject_out_of_order: bool = Field(
        default=True,
        description="Whether to reject out-of-order messages"
    )

    deduplication_cache_size: int = Field(
        gt=0,
        description="Maximum number of processed event IDs kept for duplicate detection"
    )

    status_publish_interval_seconds: int = Field(
        gt=0,
        description="Interval in seconds for publishing status messages"
    )

    alert_cooldown_seconds: int = Field(
        ge=0,
        description="Cooldown period in seconds between alert messages"
    )

    source_event_id_limit: int = Field(
        gt=0,
        description="Maximum number of source event IDs included in processed outputs"
    )

    @model_validator(mode="after")
    def validate_required_sensor_types(self) -> ProcessingSettings:
        """Ensure required sensor types do not contain duplicates."""
        if len(self.required_sensor_types) != len(
            set(self.required_sensor_types)
        ):
            raise ValueError("required_sensor_types must not contain duplicates")
        return self


# Raw values used to convert each sensor measurement to a 0-100 score.
class RiskNormalisationSettings(BaseModel):
    """Risk normalization settings for the FloodGuard fog node"""

    water_level_critical_cm: float = Field(
        gt=0,
        description="Critical water level in centimeters for risk normalization"
    )

    rainfall_critical_mm_h: float = Field(
        gt=0,
        description="Critical rainfall in millimeters per hour for risk normalization"
    )

    water_rise_rate_critical_cm_min: float = Field(
        gt=0,
        description="Critical water rise rate in centimeters per minute for risk normalization"
    )

    drain_blockage_critical_percent: float = Field(
        gt=0,
        description="Critical drain blockage percentage for risk normalization"
    )

    soil_saturation_critical_percent: float = Field(
        gt=0,
        description="Critical soil saturation percentage for risk normalization"
    )

    drainage_stress_critical: float = Field(
        gt=0,
        description="Critical drainage stress value for risk normalization"
    )


# Relative importance of each component in the final weighted score.
class RiskWeights(BaseModel):
    """Weights applied to the normalised flood-risk components."""

    water_level: float = Field(
        ge=0,
        le=1,
        description="Weight for water level in risk calculation"
    )

    rainfall: float = Field(
        ge=0,
        le=1,
        description="Weight for rainfall in risk calculation"
    )

    water_rise_rate: float = Field(
        ge=0,
        le=1,
        description="Weight for water rise rate in risk calculation"
    )

    drain_blockage: float = Field(
        ge=0,
        le=1,
        description="Weight for drain blockage in risk calculation"
    )

    soil_saturation: float = Field(
        ge=0,
        le=1,
        description="Weight for soil saturation in risk calculation"
    )

    drainage_stress: float = Field(
        ge=0,
        le=1,
        description="Weight for drainage stress in risk calculation"
    )

    @model_validator(mode="after")
    def validate_total_weight(self) -> RiskWeights:
        """Ensure risk weights sum to one."""
        total_weight = (
            self.water_level
            + self.rainfall
            + self.water_rise_rate
            + self.drain_blockage
            + self.soil_saturation
            + self.drainage_stress
        )

        # Floating point arithmetic can introduce small errors,
        # so an exact equality comparison is intentionally avoided.
        if abs(total_weight - 1.0) > 1e-9:
            raise ValueError(
                f"Risk weights must sum to 1.0, received {total_weight}"
            )
        return self


# Boundaries that map a score to NORMAL, WATCH, WARNING, HIGH, or CRITICAL.
class RiskLevelThresholds(BaseModel):
    """Thresholds for determining risk levels based on calculated risk score."""

    watch_min: float = Field(
        ge=0,
        le=100,
        description="Minimum threshold for watch risk level"
    )

    warning_min: float = Field(
        ge=0,
        le=100,
        description="Minimum threshold for warning risk level"
    )

    high_min: float = Field(
        ge=0,
        le=100,
        description="Minimum threshold for high risk level"
    )

    critical_min: float = Field(
        ge=0,
        le=100,
        description="Minimum threshold for critical risk level"
    )

    @model_validator(mode="after")
    def validate_threshold_order(self) -> RiskLevelThresholds:
        """Ensure thresholds are in ascending order."""

        if not (
            self.watch_min
            < self.warning_min
            < self.high_min
            < self.critical_min
        ):
            raise ValueError(
                "Risk level thresholds must be in ascending order: "
                "watch_min < warning_min < high_min < critical_min"
            )
        return self


# Safety rules that can raise the level even when the weighted score is lower.
class RiskOverrides(BaseModel):
    """Overrides for risk level thresholds based on specific conditions."""

    water_level_critical_cm: float = Field(
        gt=0,
        description="Override threshold for water level risk"
    )

    combined_water_level_critical_cm: float = Field(
        gt=0,
        description="Override threshold for combined water level risk"
    )

    combined_blockage_critical_percent: float = Field(
        ge=0,
        le=100,
        description="Override threshold for combined blockage risk"
    )

    rapid_rise_high_cm_min: float = Field(
        gt=0,
        description="Override threshold for rapid rise risk"
    )

    heavy_rainfall_high_mm_h: float = Field(
        gt=0,
        description="Override threshold for heavy rainfall risk"
    )

    soil_saturation_high_percent: float = Field(
        ge=0,
        le=100,
        description="Override threshold for soil saturation risk"
    )

    heavy_rainfall_critical_mm_h: float = Field(
        gt=0,
        description="Override threshold for critical heavy rainfall risk"
    )

    blockage_critical_percent: float = Field(
        ge=0,
        le=100,
        description="Override threshold for critical blockage risk"
    )


# Complete risk-engine configuration.
class RiskSettings(BaseModel):
    """Risk settings for the FloodGuard fog node"""

    flow_capacity_l_s: float = Field(
       gt=0,
       description="Flow capacity in litres per second for risk calculation",
    )


    normalisation: RiskNormalisationSettings
    weights: RiskWeights
    level_thresholds: RiskLevelThresholds
    overrides: RiskOverrides


# Local SQLite persistence settings.
class PersistenceSettings(BaseModel):
    """Persistence settings for the FloodGuard fog node"""

    database_path: str = Field(
        min_length=1,
        description="Path to the SQLite database file for persistence"
    )


# Application log verbosity.
class LoggingSettings(BaseModel):
    """Logging settings for the FloodGuard fog node"""

    level: Literal[
        "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"
    ] = Field(
        default="INFO",
        description="Logging level for the application"
    )


# Root object combining every configuration section.
class FogConfig(BaseModel):
    """Completed validated configuration for the FloodGuard fog node"""

    fog_node_id: str = Field(
        min_length=1,
        description="Unique identifier for the FloodGuard fog node"
    )

    zones: list[str] = Field(
        min_length=1,
        description="List of zones the fog node is responsible for"
    )


    mqtt: MqttSettings
    processing: ProcessingSettings
    risk: RiskSettings
    persistence: PersistenceSettings
    logging: LoggingSettings

    @model_validator(mode="after")
    def validate_zones(self) -> FogConfig:
        """Ensure zones do not contain duplicates."""

        if any(not zone.strip() for zone in self.zones):
            raise ValueError("Zones must not contain empty strings or whitespace-only strings")

        if len(self.zones) != len(set(self.zones)):
            raise ValueError("Zones must not contain duplicates")

        return self


# Default configuration file path relative to this settings.py file
# rather than the current working directory, to ensure consistent behavior
DEFAULT_CONFIG_PATH = Path(__file__).with_name("fog_config.json")

def load_fog_config(
        config_path: str | Path | None = None
)-> FogConfig:
    """Load and validate the fog-node JSON configuration."""

    path = (
        Path(config_path)
        if config_path is not None
        else DEFAULT_CONFIG_PATH
    )

    # Report file and JSON errors clearly before Pydantic validates fields.
    try:
        raw_config = json.loads(
            path.read_text(encoding="utf-8")
        )
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"Configuration file not found at {path}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Configuration file at {path} is not valid JSON"
        ) from exc

    # Validate nested types, numeric ranges, and cross-field rules.
    return FogConfig.model_validate(raw_config)
