"""Simple sensor simulator for FloodGuard Edge device."""
import json
import logging
import random
import time
from datetime import datetime, timezone
from pathlib import Path
import paho.mqtt.client as mqtt
from shared.telemetry import TelemetryMessage

# locate config.json in the same directory as this Python file
CONFIG_PATH = Path(__file__).with_name("config.json")

# Configure logging format used throughout the simulator
# Info records nomal operations, while error records failures to connect to the MQTT broker
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
# Create a logger specific for this Python module.
logger = logging.getLogger(__name__)


def load_config() -> dict:
    """Load configuration from config.json file."""
    content = CONFIG_PATH.read_text(encoding="utf-8")
    return json.loads(content)

def generate_sensor_value(config: dict, sensor_type: str, sequence: int) -> float:
    """Generate a sensor value according to the selected scenario and sensor type."""
    profile = config["sensor_profiles"][sensor_type]
    scenario = config["simulation"]["scenario"]

    # Generate the baseline value using the configured sensor limits.
    baseline_value = random.uniform(
        profile["min_value"],
        profile["max_value"]
        )

    # Read the final multiplier for the selected scenario and sensor.
    target_multiplier = config["scenario_multipliers"][scenario][sensor_type]
    number_of_samples = config["simulation"]["readings_per_sensor"]

    # Calculate the multiplier for the current reading based on the sequence number.
    if number_of_samples == 1:
        multiplier = 1.0
    else:
        multiplier = (sequence - 1) / (number_of_samples - 1)

    # Gradually adjust the baseline value towards the target multiplier.
    current_multiplier = 1.0 + (target_multiplier - 1.0) * multiplier

    return round(baseline_value * current_multiplier, 2)

def build_sensor_message(
        config: dict, zone_id: str, sensor_type: str, sequence: int,) -> dict:
    """Build a sensor message with the given configuration, zone ID, sensor type, and sequence number."""
    profile = config["sensor_profiles"][sensor_type]

    message = TelemetryMessage(
        device_id=f'{zone_id}-{sensor_type}-01',
        zone_id=zone_id,
        sensor_type=sensor_type,
        value=generate_sensor_value(config=config, sensor_type=sensor_type, sequence=sequence),
        unit=profile["unit"],
        sequence=sequence,
        timestamp=datetime.now(timezone.utc)
    )

    return message.model_dump(mode="json")

def build_sensor_topic(config: dict, zone_id: str, sensor_type: str) -> str:
    """Build the MQTT topic for sensor messages based on the configuration, zone ID, and sensor type."""
    prefix = config["mqtt"]["topic_prefix"]

    return f"{prefix}/{zone_id}/{sensor_type}/telemetry"

def create_mqtt_client(config: dict) -> mqtt.Client:
    """Create and configure an MQTT client based on the configuration."""
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

    client.connect(
        host=config["mqtt"]["host"],
        port=config["mqtt"]["port"],
        keepalive=config["mqtt"]["keepalive"]
    )

    client.loop_start()

    return client

if __name__ == "__main__":
    config = load_config()
    random.seed(config["simulation"]["random_seed"])

    number_of_samples = config["simulation"]["readings_per_sensor"]
    interval = config["simulation"]["interval_seconds"]
    zones = config["zones"]
    sensor_types = list(config['sensor_profiles'])

    # Attempt to connect to the local MQTT broker.
    # If the connection fails, log the error and exit the program.
    try:
        client = create_mqtt_client(config)
    except OSError as error:
        logger.error(
            "Failed to connect to MQTT broker: %s",
            error,
        )
        raise SystemExit(1) from error

    logger.info("Configured zones: %s", zones)
    logger.info("Configured sensors: %s", sensor_types)
    logger.info("Number of samples per sensor: %d", number_of_samples)
    time.sleep(1)  # Allow time for the MQTT client to connect

    logger.info('MQTT client connected: %s', client.is_connected())

    # Run the simulation until all readings are published for all zones and sensor types.
    try:
        for zone_id in zones:
            logger.info('Processing zone: %s', zone_id)

            for sensor_type in sensor_types:
                topic = build_sensor_topic(
                    config=config,
                    zone_id=zone_id,
                    sensor_type=sensor_type
            )

                logger.info('Publishing to MQTT topic: %s', topic)


                for number in range(1, number_of_samples + 1):
                    message = build_sensor_message(
                        config=config,
                        zone_id=zone_id,
                        sensor_type=sensor_type,
                        sequence=number
                    )

                    payload = json.dumps(message)

                    result = client.publish(
                        topic=topic,
                        payload=payload,
                        qos=config["mqtt"]["qos"],
                    )

                    result.wait_for_publish()

                    logger.info("Published message %s to topic %s", number, topic)
                    logger.info("Waiting %s seconds before publishing the next message...", interval)
                    time.sleep(interval)
        logger.info('Simulation completed successfully.')

    except KeyboardInterrupt:
        # Handle Ctrl+C gracefully without displaying a traceback.
        logger.info("Simulation interrupted by user.")

    finally:
        # Always stop the MQTT network loop and disconnect the client.        client.loop_stop()
        client.disconnect()

        logger.info("MQTT client disconnected safely.")