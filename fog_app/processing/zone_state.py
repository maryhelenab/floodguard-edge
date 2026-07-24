"""Maintain independent rolling sensor windows for every monitored zone."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import fmean
from typing import cast, get_args

from shared.telemetry import SensorType, TelemetryMessage


def _all_sensor_types() -> tuple[SensorType, ...]:
    """Return all sensor types supported by the shared telemetry schema."""

    return tuple(
        cast(SensorType, sensor_type)
        for sensor_type in get_args(SensorType)
    )


@dataclass(frozen=True, slots=True)
class SensorWindowStatistics:
    """Summary statistics calculated from one sensor window."""

    latest_value: float
    average_value: float
    minimum_value: float
    maximum_value: float
    sample_count: int


@dataclass(slots=True)
# Time-bounded readings for one sensor type.
class SensorWindow:
    """Maintain telemetry inside a fixed time-based rolling window."""

    window_seconds: int
    _readings: list[TelemetryMessage] = field(
        default_factory=list,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        """Validate the configured rolling-window duration."""

        if self.window_seconds < 1:
            raise ValueError("Rolling-window duration must be at least 1 second.")

    def __len__(self) -> int:
        """Return the number of readings currently inside the window."""

        return len(self._readings)

    @property
    def readings(self) -> tuple[TelemetryMessage, ...]:
        """Return an immutable snapshot of the current readings."""

        return tuple(self._readings)

    @property
    def latest(self) -> TelemetryMessage | None:
        """Return the most recent timestamped reading."""

        if not self._readings:
            return None

        return self._readings[-1]

    def add(self, telemetry: TelemetryMessage) -> None:
        """Add telemetry and remove readings outside the time window."""

        # Sort by sensor time because messages can arrive slightly out of order.
        self._readings.append(telemetry)
        self._readings.sort(key=lambda reading: reading.timestamp)

        latest_timestamp = self._readings[-1].timestamp
        cutoff_timestamp = latest_timestamp - timedelta(
            seconds=self.window_seconds
        )

        # Remove readings that fall outside the configured rolling window.
        self._readings = [
            reading
            for reading in self._readings
            if reading.timestamp >= cutoff_timestamp
        ]

    def statistics(self) -> SensorWindowStatistics | None:
        """Calculate summary statistics for the current window."""

        if not self._readings:
            return None

        values = [reading.value for reading in self._readings]

        return SensorWindowStatistics(
            latest_value=self._readings[-1].value,
            average_value=fmean(values),
            minimum_value=min(values),
            maximum_value=max(values),
            sample_count=len(values),
        )

    def rate_per_minute(self, minimum_samples: int = 2) -> float:
        """Calculate value change per minute using timestamps."""

        if minimum_samples < 2:
            raise ValueError("At least two samples are required for a trend.")

        if len(self._readings) < minimum_samples:
            return 0.0

        oldest_reading = self._readings[0]
        latest_reading = self._readings[-1]

        elapsed_seconds = (
            latest_reading.timestamp - oldest_reading.timestamp
        ).total_seconds()

        if elapsed_seconds <= 0:
            return 0.0

        elapsed_minutes = elapsed_seconds / 60.0

        return (
            latest_reading.value - oldest_reading.value
        ) / elapsed_minutes


@dataclass(slots=True)
# Complete local state for one geographic drainage zone.
class ZoneState:
    """Maintain all local fog-processing state for one urban zone."""

    zone_id: str
    rolling_window_seconds: int
    required_sensor_types: tuple[SensorType, ...] = field(
        default_factory=_all_sensor_types
    )

    current_risk_score: float | None = None
    current_risk_level: str = "INITIALISING"
    previous_risk_level: str | None = None

    last_status_publication_time: datetime | None = None
    last_alert_publication_time: datetime | None = None
    most_recent_alert_severity: str | None = None

    accepted_readings: int = 0
    rejected_readings: int = 0
    last_accepted_telemetry_time: datetime | None = None

    latest_readings: dict[SensorType, TelemetryMessage] = field(
        default_factory=dict,
        init=False,
    )

    _windows: dict[SensorType, SensorWindow] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        """Validate the zone and create one window for every sensor type."""

        if not self.zone_id.strip():
            raise ValueError("Zone ID cannot be empty.")

        if self.rolling_window_seconds < 1:
            raise ValueError(
                "Rolling-window duration must be at least 1 second."
            )

        if len(self.required_sensor_types) != len(
            set(self.required_sensor_types)
        ):
            raise ValueError("Required sensor types cannot contain duplicates.")

        supported_sensor_types = set(_all_sensor_types())

        if not set(self.required_sensor_types).issubset(
            supported_sensor_types
        ):
            raise ValueError("Required sensor types contain unsupported values.")

        # Keep a separate rolling window for every supported sensor type.
        self._windows = {
            sensor_type: SensorWindow(self.rolling_window_seconds)
            for sensor_type in _all_sensor_types()
        }

    def add_telemetry(self, telemetry: TelemetryMessage) -> None:
        """Add accepted telemetry to the correct sensor window."""

        if telemetry.zone_id != self.zone_id:
            raise ValueError(
                "Telemetry cannot be added to a different zone state."
            )

        sensor_window = self._windows.get(telemetry.sensor_type)

        if sensor_window is None:
            raise ValueError(
                f"Unsupported sensor type: {telemetry.sensor_type!r}"
            )

        # Update only the window that matches this message.
        sensor_window.add(telemetry)

        latest_reading = sensor_window.latest

        if latest_reading is not None:
            self.latest_readings[telemetry.sensor_type] = latest_reading

        self.accepted_readings += 1

        if (
            self.last_accepted_telemetry_time is None
            or telemetry.timestamp > self.last_accepted_telemetry_time
        ):
            self.last_accepted_telemetry_time = telemetry.timestamp

    def record_rejection(self) -> None:
        """Increase the number of rejected readings for this zone."""

        self.rejected_readings += 1

    def window_for(self, sensor_type: SensorType) -> SensorWindow:
        """Return the rolling window belonging to one sensor type."""

        try:
            return self._windows[sensor_type]
        except KeyError as error:
            raise ValueError(
                f"Unsupported sensor type: {sensor_type!r}"
            ) from error

    def statistics_for(
        self,
        sensor_type: SensorType,
    ) -> SensorWindowStatistics | None:
        """Return summary statistics for one sensor type."""

        return self.window_for(sensor_type).statistics()

    def missing_sensor_types(self) -> tuple[SensorType, ...]:
        """Return required sensor types that have not produced a reading."""

        return tuple(
            sensor_type
            for sensor_type in self.required_sensor_types
            if sensor_type not in self.latest_readings
        )

    def is_initialising(self) -> bool:
        """Return whether the zone is still waiting for required sensors."""

        return bool(self.missing_sensor_types())

    def water_level_rate_of_rise(
        self,
        minimum_samples: int = 2,
    ) -> float:
        """Calculate water-level change in centimetres per minute."""

        return self.window_for("water_level").rate_per_minute(
            minimum_samples=minimum_samples
        )