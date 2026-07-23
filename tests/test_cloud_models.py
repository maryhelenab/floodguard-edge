"""Essential tests for the Day 3 cloud components."""

import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from backend.cloud_bridge import CloudBridge
from backend.cloud_models import (
    CloudEventEnvelope,
    read_fog_topic,
)
from backend.config import BackendSettings
from fog_app.models import (
    DerivedMetrics,
    FogAlert,
    FogStatus,
    SampleCounts,
    SensorSnapshot,
)


NOW = datetime.now(timezone.utc)

STATUS_TOPIC = (
    "city/drainage/dublin-zone-01/fog/status"
)

ALERT_TOPIC = (
    "city/drainage/dublin-zone-01/fog/alert"
)


def make_status(
    zone_id: str = "dublin-zone-01",
) -> FogStatus:
    """Create one valid status for the tests."""

    return FogStatus(
        fog_node_id="fog-node-dublin-01",
        zone_id=zone_id,
        risk_level="WARNING",
        risk_score=64.5,
        computed_at=NOW,
        window_seconds=60,
        sensor_snapshot=SensorSnapshot(
            rainfall=42.0,
            water_level=51.0,
            flow_rate=16.0,
            soil_saturation=72.0,
            drain_blockage=61.0,
        ),
        derived_metrics=DerivedMetrics(
            water_rise_cm_min=4.2,
            flow_utilisation_percent=53.0,
            drainage_stress_score=58.0,
        ),
        sample_counts=SampleCounts(
            rainfall=5,
            water_level=5,
            flow_rate=5,
            soil_saturation=5,
            drain_blockage=5,
        ),
        reasons=["Elevated flood risk."],
        source_event_ids=[uuid4()],
    )


def make_alert() -> FogAlert:
    """Create one valid alert for the tests."""

    return FogAlert(
        fog_node_id="fog-node-dublin-01",
        zone_id="dublin-zone-01",
        severity="CRITICAL",
        risk_score=91.2,
        triggered_at=NOW,
        message="Critical flooding risk detected.",
        reasons=["Critical water level."],
        recommended_action=(
            "Inspect the drainage zone immediately."
        ),
        source_status_event_id=uuid4(),
    )


class FakeSqsClient:
    """Record messages without connecting to AWS."""

    def __init__(self) -> None:
        self.messages = []

    def send_message(
        self,
        **message,
    ):
        self.messages.append(message)

        return {
            "MessageId": "test-message-id"
        }


class FakeMqttClient:
    """Minimal MQTT client used by the bridge test."""

    on_connect = None
    on_message = None


def test_reads_status_topic() -> None:
    zone_id, event_type = read_fog_topic(
        STATUS_TOPIC
    )

    assert zone_id == "dublin-zone-01"
    assert event_type == "status"


def test_reads_alert_topic() -> None:
    zone_id, event_type = read_fog_topic(
        ALERT_TOPIC
    )

    assert zone_id == "dublin-zone-01"
    assert event_type == "alert"


def test_rejects_invalid_topic() -> None:
    with pytest.raises(ValueError):
        read_fog_topic(
            "city/drainage/dublin-zone-01/invalid"
        )


def test_creates_status_cloud_event() -> None:
    event = CloudEventEnvelope.from_mqtt(
        STATUS_TOPIC,
        make_status().model_dump_json(),
    )

    assert event.event_type == "status"
    assert event.zone_id == "dublin-zone-01"


def test_creates_alert_cloud_event() -> None:
    event = CloudEventEnvelope.from_mqtt(
        ALERT_TOPIC,
        make_alert().model_dump_json(),
    )

    assert event.event_type == "alert"
    assert event.zone_id == "dublin-zone-01"


def test_rejects_zone_mismatch() -> None:
    status = make_status(
        zone_id="dublin-zone-02"
    )

    with pytest.raises(
        ValueError,
        match="does not match",
    ):
        CloudEventEnvelope.from_mqtt(
            STATUS_TOPIC,
            status.model_dump_json(),
        )


def test_bridge_sends_event_to_sqs() -> None:
    fake_sqs = FakeSqsClient()

    settings = BackendSettings(
        aws_region="us-east-1",
        sqs_queue_url=(
            "https://example.com/floodguard-events"
        ),
    )

    bridge = CloudBridge(
        settings,
        sqs_client=fake_sqs,
        mqtt_client=FakeMqttClient(),
    )

    event = CloudEventEnvelope.from_mqtt(
        STATUS_TOPIC,
        make_status().model_dump_json(),
    )

    message_id = bridge.send_to_sqs(event)

    body = json.loads(
        fake_sqs.messages[0]["MessageBody"]
    )

    assert message_id == "test-message-id"
    assert body["event_type"] == "status"
