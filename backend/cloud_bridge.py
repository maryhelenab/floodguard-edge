"""Forward validated fog-node MQTT outputs to Amazon SQS.

The bridge separates the local fog layer from the scalable AWS backend:
MQTT provides low-latency local messaging, while SQS provides durable cloud
buffering and retry support.
"""

import logging

import boto3
import paho.mqtt.client as mqtt

from backend.cloud_models import CloudEventEnvelope
from backend.config import BackendSettings, load_backend_settings


LOGGER = logging.getLogger(__name__)


class CloudBridge:
    """Connect the local MQTT broker to the cloud SQS queue."""

    def __init__(
        self,
        settings: BackendSettings,
        sqs_client=None,
        mqtt_client=None,
    ) -> None:
        """Create the AWS and MQTT clients used by the bridge.
        Optional clients are accepted so automated tests can use safe fakes
        instead of connecting to real AWS or MQTT services.
        """

        self.settings = settings

        # Reuse an injected test client or create the real regional SQS client.
        self.sqs_client = sqs_client or boto3.client(
            "sqs",
            region_name=settings.aws_region,
        )

        # MQTT callback API version 2 provides the modern callback signatures.
        self.mqtt_client = mqtt_client or mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=settings.cloud_bridge_client_id,
        )

        # Register callbacks before opening the network connection.
        self.mqtt_client.on_connect = self._on_connect
        self.mqtt_client.on_message = self._on_message

    def _on_connect(
        self,
        client,
        userdata,
        flags,
        reason_code,
        properties,
    ) -> None:
        """Subscribe to fog status and alert topics after MQTT connects."""

        # A non-zero reason code means the broker rejected the connection.
        if reason_code != 0:
            LOGGER.error(
                "MQTT connection failed: %s",
                reason_code,
            )
            return

        # Status and alerts are separate topics but both are forwarded to SQS.
        client.subscribe(
            self.settings.mqtt_status_topic,
            qos=self.settings.mqtt_qos,
        )
        client.subscribe(
            self.settings.mqtt_alert_topic,
            qos=self.settings.mqtt_qos,
        )

        LOGGER.info("Cloud bridge subscribed to fog outputs.")

    def _on_message(
        self,
        client,
        userdata,
        message,
    ) -> None:
        """Validate one MQTT message and forward it to SQS."""

        # The callback must not crash the MQTT loop when one bad message arrives.
        try:
            event = CloudEventEnvelope.from_mqtt(
                message.topic,
                message.payload,
            )
            self.send_to_sqs(event)
        except Exception as error:
            LOGGER.error(
                "Could not process MQTT message: %s",
                error,
            )

    def send_to_sqs(self, event: CloudEventEnvelope) -> str:
        """Send one validated cloud event and return its SQS message ID."""

        # Pydantic serialises UUID and datetime fields safely to JSON.
        response = self.sqs_client.send_message(
            QueueUrl=self.settings.sqs_queue_url,
            MessageBody=event.model_dump_json(),
        )

        message_id = response["MessageId"]

        LOGGER.info(
            "Event sent to SQS: message_id=%s, type=%s, zone=%s",
            message_id,
            event.event_type,
            event.zone_id,
        )

        return message_id

    def run(self) -> None:
        """Connect to MQTT and keep processing messages until stopped."""

        LOGGER.info(
            "Starting cloud bridge on %s:%s",
            self.settings.mqtt_host,
            self.settings.mqtt_port,
        )

        self.mqtt_client.connect(
            self.settings.mqtt_host,
            self.settings.mqtt_port,
            60,
        )

        # loop_forever handles reconnects and continuously runs callbacks.
        self.mqtt_client.loop_forever()


def main() -> None:
    """Configure logging, load settings, and start the bridge process."""

    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s | %(levelname)s | "
            "%(name)s | %(message)s"
        ),
    )

    settings = load_backend_settings()
    bridge = CloudBridge(settings)
    bridge.run()


if __name__ == "__main__":
    main()
