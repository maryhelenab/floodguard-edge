"""Send fog MQTT outputs to Amazon SQS."""

import logging

import boto3
import paho.mqtt.client as mqtt

from backend.cloud_models import (
    CloudEventEnvelope,
)
from backend.config import (
    BackendSettings,
    load_backend_settings,
)


LOGGER = logging.getLogger(__name__)


class CloudBridge:
    """Connect the local MQTT broker to Amazon SQS."""

    def __init__(
        self,
        settings: BackendSettings,
        sqs_client=None,
        mqtt_client=None,
    ) -> None:
        self.settings = settings

        self.sqs_client = (
            sqs_client
            or boto3.client(
                "sqs",
                region_name=settings.aws_region,
            )
        )

        self.mqtt_client = (
            mqtt_client
            or mqtt.Client(
                callback_api_version=(
                    mqtt.CallbackAPIVersion.VERSION2
                ),
                client_id=(
                    settings.cloud_bridge_client_id
                ),
            )
        )

        self.mqtt_client.on_connect = (
            self._on_connect
        )

        self.mqtt_client.on_message = (
            self._on_message
        )

    def _on_connect(
        self,
        client,
        userdata,
        flags,
        reason_code,
        properties,
    ) -> None:
        """Subscribe when MQTT connects successfully."""

        if reason_code != 0:
            LOGGER.error(
                "MQTT connection failed: %s",
                reason_code,
            )
            return

        client.subscribe(
            self.settings.mqtt_status_topic,
            qos=self.settings.mqtt_qos,
        )

        client.subscribe(
            self.settings.mqtt_alert_topic,
            qos=self.settings.mqtt_qos,
        )

        LOGGER.info(
            "Cloud bridge subscribed to fog outputs."
        )

    def _on_message(
        self,
        client,
        userdata,
        message,
    ) -> None:
        """Receive one MQTT message and send it to SQS."""

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

    def send_to_sqs(
        self,
        event: CloudEventEnvelope,
    ) -> str:
        """Send one validated event to Amazon SQS."""

        response = self.sqs_client.send_message(
            QueueUrl=self.settings.sqs_queue_url,
            MessageBody=event.model_dump_json(),
        )

        message_id = response["MessageId"]

        LOGGER.info(
            "Event sent to SQS: "
            "message_id=%s, type=%s, zone=%s",
            message_id,
            event.event_type,
            event.zone_id,
        )

        return message_id

    def run(self) -> None:
        """Start the MQTT bridge."""

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

        self.mqtt_client.loop_forever()


def main() -> None:
    """Run the cloud bridge process."""

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
