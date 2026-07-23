"""MQTT adapter for the FloodGuard fog-processing pipeline."""

import logging

import paho.mqtt.client as mqtt

from fog_app.config.settings import FogConfig, load_fog_config
from fog_app.persistence import FogEventStore
from fog_app.processing.processor import FogProcessor


LOGGER = logging.getLogger(__name__)


class FogMqttNode:
    """Receive raw telemetry and publish processed status and alerts."""

    def __init__(
        self,
        config: FogConfig,
        *,
        processor: FogProcessor | None = None,
        client: mqtt.Client | None = None,
    ) -> None:
        """Create the MQTT adapter and register its callbacks."""

        self.config = config

        if processor is None:
            event_store = FogEventStore(
                config.persistence.database_path
            )
            processor = FogProcessor(
                config,
                event_store=event_store,
            )

        self.processor = processor

        self.client = client or mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=(
                f"{config.mqtt.client_id_prefix}-"
                f"{config.fog_node_id}"
            ),
        )

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata,
        flags,
        reason_code,
        properties,
    ) -> None:
        """Subscribe to raw telemetry after connecting."""

        if reason_code != 0:
            LOGGER.error(
                "MQTT connection failed with reason code %s.",
                reason_code,
            )
            return

        topic = self.config.mqtt.telemetry_subscription_topic
        qos = self.config.mqtt.qos

        client.subscribe(topic, qos=qos)

        LOGGER.info(
            "Fog node connected and subscribed to %s with QoS %s.",
            topic,
            qos,
        )

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata,
        disconnect_flags,
        reason_code,
        properties,
    ) -> None:
        """Log MQTT disconnections."""

        if reason_code != 0:
            LOGGER.warning(
                "Unexpected MQTT disconnection: %s.",
                reason_code,
            )
        else:
            LOGGER.info("Fog node disconnected from MQTT broker.")

    def _on_message(
        self,
        client: mqtt.Client,
        userdata,
        message,
    ) -> None:
        """Process one incoming MQTT telemetry message."""

        result = self.processor.process_message(
            message.topic,
            message.payload,
        )

        if not result.accepted:
            LOGGER.warning(
                "Rejected MQTT message from %s: %s.",
                message.topic,
                result.rejection_reason,
            )
            return

        if result.status is not None:
            status_topic = (
                self.config.mqtt.status_topic_template.format(
                    zone_id=result.status.zone_id
                )
            )

            self._publish(
                client,
                topic=status_topic,
                payload=result.status.model_dump_json(),
            )

        if result.alert is not None:
            alert_topic = (
                self.config.mqtt.alert_topic_template.format(
                    zone_id=result.alert.zone_id
                )
            )

            self._publish(
                client,
                topic=alert_topic,
                payload=result.alert.model_dump_json(),
            )

    def _publish(
        self,
        client: mqtt.Client,
        *,
        topic: str,
        payload: str,
    ) -> None:
        """Publish one processed fog output."""

        publish_result = client.publish(
            topic,
            payload=payload,
            qos=self.config.mqtt.qos,
            retain=self.config.mqtt.retain_outputs,
        )

        if publish_result.rc != mqtt.MQTT_ERR_SUCCESS:
            LOGGER.error(
                "Failed to publish MQTT output to %s. Result code: %s",
                topic,
                publish_result.rc,
            )
            return

        LOGGER.info("Published fog output to %s.", topic)

    def run(self) -> None:
        """Connect to the local broker and process messages continuously."""

        LOGGER.info(
            "Starting fog node %s using broker %s:%s.",
            self.config.fog_node_id,
            self.config.mqtt.host,
            self.config.mqtt.port,
        )

        self.client.connect(
            self.config.mqtt.host,
            self.config.mqtt.port,
            self.config.mqtt.keepalive,
        )
        self.client.loop_forever()


def main() -> None:
    """Load configuration and start the MQTT fog node."""

    config = load_fog_config()

    logging.basicConfig(
        level=getattr(
            logging,
            config.logging.level.upper(),
            logging.INFO,
        ),
        format=(
            "%(asctime)s | %(levelname)s | "
            "%(name)s | %(message)s"
        ),
    )

    FogMqttNode(config).run()


if __name__ == "__main__":
    main()