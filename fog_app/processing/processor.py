"""Run the complete local fog-processing pipeline for one MQTT message.

This class is intentionally independent of the MQTT client. That separation makes
the validation, rolling state, risk logic, output policy, and persistence easy to
test without a live broker.
"""

import json
import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import cast

from pydantic import ValidationError

from fog_app.config.settings import FogConfig
from fog_app.models import (
    AlertSeverity,
    DerivedMetrics,
    FogAlert,
    FogStatus,
    SampleCounts,
    SensorSnapshot,
    StatusRiskLevel,
)
from fog_app.mqtt.topic_parser import (
    InvalidTelemetryTopicError,
    TelemetryTopicMismatchError,
    parse_telemetry_topic,
    validate_topic_matches_payload,
)
from fog_app.persistence import FogEventStore
from fog_app.processing.deduplication import EventIdDeduplicator
from fog_app.processing.message_validation import (
    DeviceSequenceTracker,
    MessageTimestampError,
    is_stale_message,
)
from fog_app.processing.publication_policy import (
    should_publish_alert,
    should_publish_status,
)
from fog_app.processing.risk_engine import (
    RiskInputs,
    calculate_drainage_metrics,
    calculate_flood_risk,
)
from fog_app.processing.zone_state import ZoneState
from shared.telemetry import SensorType, TelemetryMessage


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
# Lightweight operational metrics useful for logs, tests, and monitoring.
class FogRuntimeCounters:
    """Runtime processing counters."""

    received: int = 0
    accepted: int = 0
    invalid_json: int = 0
    validation_failures: int = 0
    topic_failures: int = 0
    duplicates: int = 0
    stale: int = 0
    out_of_order: int = 0
    risk_calculations: int = 0
    statuses_created: int = 0
    alerts_created: int = 0
    database_failures: int = 0


@dataclass(frozen=True, slots=True)
# A single return object clearly describes acceptance and optional outputs.
class ProcessingResult:
    """Outcome of processing one MQTT telemetry message."""

    accepted: bool
    rejection_reason: str | None = None
    telemetry: TelemetryMessage | None = None
    status: FogStatus | None = None
    alert: FogAlert | None = None


class FogProcessor:
    """Connect validation, state, risk, output, and persistence."""

    def __init__(
        self,
        config: FogConfig,
        *,
        event_store: FogEventStore | None = None,
    ) -> None:
        """Create per-zone state and the validation helpers used at runtime."""

        self.config = config
        self.event_store = event_store
        self.counters = FogRuntimeCounters()

        # These helpers protect the pipeline from MQTT redelivery and old data.
        self.deduplicator = EventIdDeduplicator(
            config.processing.deduplication_cache_size
        )
        self.sequence_tracker = DeviceSequenceTracker()

        required_sensors = tuple(
            config.processing.required_sensor_types
        )

        # Every configured zone has isolated rolling windows and risk state.
        self.zone_states = {
            zone_id: ZoneState(
                zone_id=zone_id,
                rolling_window_seconds=(
                    config.processing.rolling_window_seconds
                ),
                required_sensor_types=required_sensors,
            )
            for zone_id in config.zones
        }

        # Keep only the most recent source IDs to explain each fog status.
        self.source_event_ids = {
            zone_id: deque(
                maxlen=config.processing.source_event_id_limit
            )
            for zone_id in config.zones
        }

    def process_message(
        self,
        topic: str,
        payload: bytes | str,
        *,
        now: datetime | None = None,
        force_status: bool = False,
    ) -> ProcessingResult:
        """Process one raw MQTT message."""

        self.counters.received += 1

        # Use UTC consistently so sensor age and publication intervals are comparable.
        current_time = now or datetime.now(timezone.utc)

        # 1. Validate the MQTT topic structure before reading its payload.
        try:
            parsed_topic = parse_telemetry_topic(topic)
        except InvalidTelemetryTopicError as error:
            return self._reject("topic_failures", "invalid_topic", str(error))

        # 2. Decode bytes and parse the raw JSON document.
        try:
            payload_text = (
                payload.decode("utf-8")
                if isinstance(payload, bytes)
                else payload
            )
            raw_payload = json.loads(payload_text)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
            return self._reject(
                "invalid_json",
                "invalid_json",
                f"Malformed JSON: {error}",
            )

        # 3. Validate required fields, ranges, sensor type, UUID, and timestamp.
        try:
            telemetry = TelemetryMessage.model_validate(raw_payload)
        except ValidationError as error:
            return self._reject(
                "validation_failures",
                "validation_failure",
                f"Invalid telemetry payload: {error}",
            )

        # 4. Ensure the topic cannot disagree with the payload identity.
        try:
            validate_topic_matches_payload(parsed_topic, telemetry)
        except TelemetryTopicMismatchError as error:
            return self._reject(
                "topic_failures",
                "topic_mismatch",
                str(error),
            )

        # 5. Reject zones that this fog node is not configured to manage.
        zone_state = self.zone_states.get(telemetry.zone_id)

        if zone_state is None:
            return self._reject(
                "validation_failures",
                "unconfigured_zone",
                f"Unconfigured zone: {telemetry.zone_id!r}",
            )

        # 6. Optional freshness check prevents delayed data changing current risk.
        if self.config.processing.stale_message_validation_enabled:
            try:
                stale = is_stale_message(
                    telemetry.timestamp,
                    self.config.processing.maximum_message_age_seconds,
                    now=current_time,
                )
            except MessageTimestampError as error:
                return self._reject(
                    "validation_failures",
                    "invalid_timestamp",
                    str(error),
                )

            if stale:
                return self._reject(
                    "stale",
                    "stale_message",
                    f"Stale event: {telemetry.event_id}",
                )

        # 7. MQTT QoS 1 can redeliver a message, so event IDs are deduplicated.
        if self.deduplicator.check_and_record(telemetry.event_id):
            return self._reject(
                "duplicates",
                "duplicate",
                f"Duplicate event: {telemetry.event_id}",
            )

        # 8. Sequence validation rejects an older device reading after a newer one.
        if (
            self.config.processing.reject_out_of_order
            and self.sequence_tracker.check_and_record(
                telemetry.device_id,
                telemetry.sequence,
            )
        ):
            return self._reject(
                "out_of_order",
                "out_of_order",
                (
                    f"Out-of-order message from {telemetry.device_id}: "
                    f"{telemetry.sequence}"
                ),
            )

        # Save the previous level before updating state; policies compare both levels.
        previous_level = cast(
            StatusRiskLevel,
            zone_state.current_risk_level,
        )

        # 9. The message is now accepted and can update the local rolling window.
        zone_state.add_telemetry(telemetry)
        self.source_event_ids[telemetry.zone_id].append(
            telemetry.event_id
        )
        self.counters.accepted += 1

        # 10. Recalculate the zone risk using the latest complete local state.
        (
            current_level,
            risk_score,
            reasons,
            missing_sensors,
            derived_metrics,
        ) = self._calculate_zone_output(zone_state)

        warm_up_completed = (
            previous_level == "INITIALISING"
            and current_level != "INITIALISING"
        )

        status = None
        alert = None

        # 11. Publish a status on important changes or at the configured interval.
        if should_publish_status(
            previous_level=previous_level,
            current_level=current_level,
            last_publication_time=(
                zone_state.last_status_publication_time
            ),
            now=current_time,
            interval_seconds=(
                self.config.processing
                .status_publish_interval_seconds
            ),
            warm_up_completed=warm_up_completed,
            force=force_status,
        ):
            status = FogStatus(
                fog_node_id=self.config.fog_node_id,
                zone_id=zone_state.zone_id,
                risk_level=current_level,
                risk_score=risk_score,
                computed_at=current_time,
                window_seconds=(
                    self.config.processing.rolling_window_seconds
                ),
                sensor_snapshot=self._snapshot(zone_state),
                derived_metrics=derived_metrics,
                sample_counts=self._sample_counts(zone_state),
                reasons=reasons,
                missing_sensor_types=missing_sensors,
                source_event_ids=list(
                    self.source_event_ids[zone_state.zone_id]
                ),
            )

            zone_state.last_status_publication_time = current_time
            self.counters.statuses_created += 1

            # Persistence is best-effort: a database error must not stop monitoring.
            if (
                self.event_store is not None
                and not self.event_store.persist_status(status)
            ):
                self.counters.database_failures += 1

        # 12. Alerts are created only when a status exists and policy allows it.
        if (
            status is not None
            and should_publish_alert(
                previous_level=previous_level,
                current_level=current_level,
                last_alert_severity=cast(
                    AlertSeverity | None,
                    zone_state.most_recent_alert_severity,
                ),
                last_alert_publication_time=(
                    zone_state.last_alert_publication_time
                ),
                now=current_time,
                cooldown_seconds=(
                    self.config.processing.alert_cooldown_seconds
                ),
            )
        ):
            severity = cast(AlertSeverity, current_level)

            alert = FogAlert(
                fog_node_id=self.config.fog_node_id,
                zone_id=zone_state.zone_id,
                severity=severity,
                risk_score=cast(float, risk_score),
                triggered_at=current_time,
                message=f"{severity.title()} flood risk detected.",
                reasons=reasons,
                recommended_action=self._recommended_action(severity),
                source_status_event_id=status.event_id,
            )

            zone_state.last_alert_publication_time = current_time
            zone_state.most_recent_alert_severity = severity
            self.counters.alerts_created += 1

            if (
                self.event_store is not None
                and not self.event_store.persist_alert(alert)
            ):
                self.counters.database_failures += 1

        # Store the result for the next message and publication-policy comparison.
        zone_state.previous_risk_level = previous_level
        zone_state.current_risk_level = current_level
        zone_state.current_risk_score = risk_score

        return ProcessingResult(
            accepted=True,
            telemetry=telemetry,
            status=status,
            alert=alert,
        )

    def _calculate_zone_output(
        self,
        zone_state: ZoneState,
    ) -> tuple[
        StatusRiskLevel,
        float | None,
        list[str],
        list[SensorType],
        DerivedMetrics,
    ]:
        """Calculate warm-up or completed risk output."""

        # A zone stays INITIALISING until every required sensor has reported.
        missing_sensors = list(zone_state.missing_sensor_types())

        water_rise = zone_state.water_level_rate_of_rise(
            self.config.processing.minimum_samples_for_trend
        )

        flow_rate = self._latest(zone_state, "flow_rate") or 0.0
        blockage = self._latest(zone_state, "drain_blockage") or 0.0

        # Derived drainage pressure can be calculated even during warm-up.
        drainage = calculate_drainage_metrics(
            flow_rate_l_s=flow_rate,
            drain_blockage_percent=blockage,
            flow_capacity_l_s=self.config.risk.flow_capacity_l_s,
        )

        derived = DerivedMetrics(
            water_rise_cm_min=water_rise,
            flow_utilisation_percent=(
                drainage.flow_utilisation_percent
            ),
            drainage_stress_score=(
                drainage.drainage_stress_score
            ),
        )

        if missing_sensors:
            return (
                "INITIALISING",
                None,
                [
                    "Waiting for required sensors: "
                    + ", ".join(missing_sensors)
                    + "."
                ],
                missing_sensors,
                derived,
            )

        # Once complete, use the deterministic weighted risk engine.
        assessment = calculate_flood_risk(
            RiskInputs(
                rainfall_mm_h=self._required(zone_state, "rainfall"),
                water_level_cm=self._required(
                    zone_state,
                    "water_level",
                ),
                flow_rate_l_s=self._required(
                    zone_state,
                    "flow_rate",
                ),
                soil_saturation_percent=self._required(
                    zone_state,
                    "soil_saturation",
                ),
                drain_blockage_percent=self._required(
                    zone_state,
                    "drain_blockage",
                ),
                water_rise_cm_min=water_rise,
            ),
            self.config.risk,
        )

        self.counters.risk_calculations += 1

        return (
            assessment.risk_level,
            assessment.risk_score,
            list(assessment.reasons),
            [],
            DerivedMetrics(
                water_rise_cm_min=water_rise,
                flow_utilisation_percent=(
                    assessment.flow_utilisation_percent
                ),
                drainage_stress_score=(
                    assessment.drainage_stress_score
                ),
            ),
        )

    @staticmethod
    def _latest(
        zone_state: ZoneState,
        sensor_type: SensorType,
    ) -> float | None:
        """Return the latest value for a sensor, or ``None`` if unavailable."""

        telemetry = zone_state.latest_readings.get(sensor_type)
        return None if telemetry is None else telemetry.value

    def _required(
        self,
        zone_state: ZoneState,
        sensor_type: SensorType,
    ) -> float:
        """Return a required value after warm-up or raise an internal error."""

        value = self._latest(zone_state, sensor_type)

        if value is None:
            raise RuntimeError(f"Missing required sensor: {sensor_type}")

        return value

    def _snapshot(self, zone_state: ZoneState) -> SensorSnapshot:
        """Build the latest raw sensor snapshot for a status message."""

        return SensorSnapshot(
            rainfall=self._latest(zone_state, "rainfall"),
            water_level=self._latest(zone_state, "water_level"),
            flow_rate=self._latest(zone_state, "flow_rate"),
            soil_saturation=self._latest(
                zone_state,
                "soil_saturation",
            ),
            drain_blockage=self._latest(
                zone_state,
                "drain_blockage",
            ),
        )

    @staticmethod
    def _sample_counts(zone_state: ZoneState) -> SampleCounts:
        """Report how many samples support each rolling-window calculation."""

        return SampleCounts(
            rainfall=len(zone_state.window_for("rainfall")),
            water_level=len(zone_state.window_for("water_level")),
            flow_rate=len(zone_state.window_for("flow_rate")),
            soil_saturation=len(
                zone_state.window_for("soil_saturation")
            ),
            drain_blockage=len(
                zone_state.window_for("drain_blockage")
            ),
        )

    @staticmethod
    def _recommended_action(severity: AlertSeverity) -> str:
        """Map each alert severity to a simple operational response."""

        actions = {
            "WARNING": "Inspect the drainage zone and monitor conditions.",
            "HIGH": "Dispatch an inspection team and prepare emergency response.",
            "CRITICAL": "Activate the local emergency response immediately.",
        }

        return actions[severity]

    def _reject(
        self,
        counter_name: str,
        reason: str,
        message: str,
    ) -> ProcessingResult:
        """Increment a rejection counter, log the reason, and return failure."""

        current_value = getattr(self.counters, counter_name)
        setattr(self.counters, counter_name, current_value + 1)

        LOGGER.warning(message)

        return ProcessingResult(
            accepted=False,
            rejection_reason=reason,
        )