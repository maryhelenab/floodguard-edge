"""Simple sensor simulator for FloodGuard Edge device."""
import json
import logging
import random
import time
from collections import deque
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

def create_sensor_queues(zones: list[str], sensor_types: list[str]) -> dict:
    """Create a dictionary of sensor queues for each zone and sensor type."""
    return {
        f'{zone_id}-{sensor_type}-01': deque()
        for zone_id in zones
        for sensor_type in sensor_types
    }

def dispatch_queued_messages(
        client: mqtt.Client,
        config: dict,
        sensor_queues: dict,
) -> int:
    """publish all messages currently stored in the local sensor queues."""
    total_dispatched = 0

    # Process the queue belonging to each simulated sensor device.
    for device_id, sensor_queue in sensor_queues.items():
        # Continue until the current device queue is empty.
        while sensor_queue:
            topic, payload = sensor_queue[0]

            result = client.publish(
                topic=topic,
                payload=payload,
                qos=config["mqtt"]["qos"],
            )

            result.wait_for_publish()

            # Remove the message from the queue after successful dispatch
            sensor_queue.popleft()
            total_dispatched += 1

            logger.info(
                "Dispatched queued messages from local queues: %s to topic %s",
                device_id,
                topic,
            )

    return total_dispatched

def run_simulation(config: dict) -> None:
    """Run the sensor simulation based on the provided configuration."""
    random.seed(config["simulation"]["random_seed"])

    number_of_samples = config["simulation"]["readings_per_sensor"]

    # Read the separate interval for telemetry generation and MQTT dispatch.
    generation_interval = config["simulation"]["generation_interval_seconds"]
    dispatch_interval = config["simulation"]["dispatch_interval_seconds"]

    zones = config["zones"]
    sensor_types = list(config["sensor_profiles"])

    # Create one unbounded local queue for each simulated sensor device.
    sensor_queues = create_sensor_queues(zones=zones, sensor_types=sensor_types)

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
    logger.info("Generation interval (seconds): %s", generation_interval)
    logger.info("Dispatch interval (seconds): %s", dispatch_interval)
    logger.info("Created %d local sensor queues", len(sensor_queues))
    time.sleep(1)  # Allow time for the MQTT client to connect

    logger.info('MQTT client connected: %s', client.is_connected())

    # Track when the last MQTT dispatch occured.
    last_dispatch_time = time.monotonic()

    # Generate telemetry and dispatch queued messages at separate intervals.
    try:
        for sequence in range(1, number_of_samples + 1):
            logger.info(
                'Generating reading batch %d of %d',
                sequence,
                number_of_samples,
            )

            # Generate one reading for each sensor type in each zone and store it in the local queue.
            for zone_id in zones:
                for sensor_type in sensor_types:
                    device_id = f'{zone_id}-{sensor_type}-01'

                    topic = build_sensor_topic(
                        config=config,
                        zone_id=zone_id,
                        sensor_type=sensor_type
                    )

                    message = build_sensor_message(
                        config=config,
                        zone_id=zone_id,
                        sensor_type=sensor_type,
                        sequence=sequence,
                    )

                    payload = json.dumps(message)

                    # Store the message in the local queue for later dispatch.
                    sensor_queues[device_id].append((topic, payload))

                    logger.info(
                        "Queued message %s for device %s",
                        sequence,
                        device_id,
                    )

            # Generation and MQTT dispatch use idenpendent timers.
            logger.info(
                "Waiting for %s seconds before the next generation cycle",
                generation_interval,
            )
            time.sleep(generation_interval)

            elapsed_since_dispatch = (
                time.monotonic() - last_dispatch_time
            )

            if elapsed_since_dispatch >= dispatch_interval:
                dispatched_count = dispatch_queued_messages(
                    client=client,
                    config=config,
                    sensor_queues=sensor_queues,
                )

                logger.info(
                    "Dispatched cycle published %d queued messages",
                    dispatched_count,
                )

                last_dispatch_time = time.monotonic()

        #Publish any messages remaining after the final generation cycle.
        remaining_count = dispatch_queued_messages(
            client=client,
            config=config,
            sensor_queues=sensor_queues,
        )

        if remaining_count > 0:
            logger.info(
                "Final dispatch published %d queued messages",
                remaining_count,
            )

        logger.info("Simulation completed successfully.")

    except KeyboardInterrupt:
        # Handle Ctrl+C gracefully without displaying a traceback.
        logger.info("Simulation interrupted by user.")

    finally:
        # Always stop the MQTT network loop and disconnect the client.
        client.loop_stop()
        client.disconnect()

        logger.info("MQTT client disconnected safely.")

if __name__ == "__main__":
    configutation = load_config()
    run_simulation(config=configutation)
