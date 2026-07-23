"""Tests for the MQTT adapter around the fog processor."""

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import paho.mqtt.client as mqtt

from fog_app.config.settings import load_fog_config
from fog_app.mqtt.fog_node import FogMqttNode
from fog_app.processing.processor import FogProcessor
from shared.telemetry import TelemetryMessage


class FakePublishResult:
    """Represent a successful fake MQTT publication."""

    rc = mqtt.MQTT_ERR_SUCCESS


class FakeMqttClient:
    """Capture subscriptions and publications without a real broker."""

    def __init__(self) -> None:
        self.subscriptions: list[tuple[str, int]] = []
        self.publications: list[tuple[str, str, int, bool]] = []

        self.on_connect = None
        self.on_disconnect = None
        self.on_message = None

    def subscribe(self, topic: str, qos: int = 0):
        """Record one MQTT subscription."""

        self.subscriptions.append((topic, qos))
        return (mqtt.MQTT_ERR_SUCCESS, 1)

    def publish(
        self,
        topic: str,
        payload: str,
        qos: int,
        retain: bool,
    ) -> FakePublishResult:
        """Record one MQTT publication."""

        self.publications.append(
            (topic, payload, qos, retain)
        )
        return FakePublishResult()


def make_rainfall_message() -> TelemetryMessage:
    """Create one fresh telemetry message."""

    return TelemetryMessage(
        event_id=uuid4(),
        device_id="dublin-zone-01-rainfall-01",
        zone_id="dublin-zone-01",
        sensor_type="rainfall",
        value=15.0,
        unit="mm/h",
        sequence=1,
        timestamp=datetime.now(timezone.utc),
    )


def test_subscribes_to_raw_telemetry_topic() -> None:
    """Subscribe using the configured wildcard topic and QoS."""

    config = load_fog_config()
    fake_client = FakeMqttClient()

    node = FogMqttNode(
        config,
        processor=FogProcessor(config),
        client=fake_client,
    )

    node._on_connect(
        fake_client,
        None,
        None,
        0,
        None,
    )

    assert fake_client.subscriptions == [
        (
            "city/drainage/+/+/telemetry",
            1,
        )
    ]


def test_valid_message_publishes_initialising_status() -> None:
    """Publish a zone status after accepting valid telemetry."""

    config = load_fog_config()
    fake_client = FakeMqttClient()

    node = FogMqttNode(
        config,
        processor=FogProcessor(config),
        client=fake_client,
    )

    telemetry = make_rainfall_message()

    message = SimpleNamespace(
        topic=(
            "city/drainage/dublin-zone-01/"
            "rainfall/telemetry"
        ),
        payload=telemetry.model_dump_json().encode("utf-8"),
    )

    node._on_message(fake_client, None, message)

    assert len(fake_client.publications) == 1

    topic, payload, qos, retain = fake_client.publications[0]

    assert topic == "city/drainage/dublin-zone-01/fog/status"
    assert '"risk_level":"INITIALISING"' in payload
    assert qos == 1
    assert retain is False


def test_invalid_json_does_not_publish_output() -> None:
    """Reject malformed JSON without publishing status or alert."""

    config = load_fog_config()
    fake_client = FakeMqttClient()

    node = FogMqttNode(
        config,
        processor=FogProcessor(config),
        client=fake_client,
    )

    message = SimpleNamespace(
        topic=(
            "city/drainage/dublin-zone-01/"
            "rainfall/telemetry"
        ),
        payload=b"{invalid-json",
    )

    node._on_message(fake_client, None, message)

    assert fake_client.publications == []