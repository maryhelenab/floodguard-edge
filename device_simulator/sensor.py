"""Generate realistic sensor readings and publish them to MQTT.

The simulator represents the IoT/device layer of FloodGuard. It can also
buffer readings locally when MQTT publication fails and retry them later.
"""

import json
import logging
import random
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt

from shared.telemetry import TelemetryMessage


# Resolve the JSON configuration beside this file, not from the shell directory.
CONFIG_PATH = Path(__file__).with_name("config.json")

# Hard limits prevent an edited configuration file from creating
# unbounded loops or excessively long sleep intervals.
MAX_READINGS_PER_SENSOR = 1000
MAX_INTERVAL_SECONDS = 3600.0


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger(__name__)


def load_config() -> dict:
    """Read the simulator settings from ``config.json``."""
    content = CONFIG_PATH.read_text(encoding="utf-8")
    return json.loads(content)


def validate_reading_count(value: object) -> int:
    """Return a safe number of readings for one simulation run."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("readings_per_sensor must be an integer.")

    if not 1 <= value <= MAX_READINGS_PER_SENSOR:
        raise ValueError(
            "readings_per_sensor must be between "
            f"1 and {MAX_READINGS_PER_SENSOR}."
        )

    return value


def validate_interval(value: object, field_name: str) -> float:
    """Return a safe non-negative simulation interval."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be numeric.")

    safe_value = float(value)

    if not 0.0 <= safe_value <= MAX_INTERVAL_SECONDS:
        raise ValueError(
            f"{field_name} must be between 0 and "
            f"{MAX_INTERVAL_SECONDS} seconds."
        )

    return safe_value


# ---------------------------------------------------------------------------
# Sensor data generation
# ---------------------------------------------------------------------------

def generate_sensor_value(
    config: dict,
    sensor_type: str,
    sequence: int,
) -> float:
    """Generate a value for the selected scenario and sensor type."""
    profile = config["sensor_profiles"][sensor_type]
    scenario = config["simulation"]["scenario"]

    baseline_value = random.uniform(
        profile["min_value"],
        profile["max_value"],
    )

    target_multiplier = config["scenario_multipliers"][scenario][sensor_type]
    number_of_samples = config["simulation"]["readings_per_sensor"]

    if number_of_samples == 1:
        progress = 1.0
    else:
        progress = (sequence - 1) / (number_of_samples - 1)

    if scenario == "developing_flood" and sensor_type == "flow_rate":
        if progress <= 0.5:
            current_multiplier = (
                1.0
                + (target_multiplier - 1.0)
                * (progress / 0.5)
            )
        else:
            decline_progress = (progress - 0.5) / 0.5
            current_multiplier = (
                target_multiplier
                - (target_multiplier - 1.0)
                * 0.5
                * decline_progress
            )
    elif scenario == "developing_flood" and sensor_type == "water_level":
        current_multiplier = (
            1.0
            + (target_multiplier - 1.0)
            * (progress ** 2)
        )
    elif scenario == "developing_flood" and sensor_type == "drain_blockage":
        current_multiplier = (
            1.0
            + (target_multiplier - 1.0)
            * (progress ** 1.5)
        )
    else:
        current_multiplier = (
            1.0
            + (target_multiplier - 1.0)
            * progress
        )

    return round(baseline_value * current_multiplier, 2)


# ---------------------------------------------------------------------------
# MQTT message construction
# ---------------------------------------------------------------------------

def build_sensor_message(
    config: dict,
    zone_id: str,
    sensor_type: str,
    sequence: int,
) -> dict:
    """Build one validated telemetry message."""
    profile = config["sensor_profiles"][sensor_type]

    message = TelemetryMessage(
        device_id=f"{zone_id}-{sensor_type}-01",
        zone_id=zone_id,
        sensor_type=sensor_type,
        value=generate_sensor_value(
            config=config,
            sensor_type=sensor_type,
            sequence=sequence,
        ),
        unit=profile["unit"],
        sequence=sequence,
        timestamp=datetime.now(timezone.utc),
    )

    return message.model_dump(mode="json")


def build_sensor_topic(
    config: dict,
    zone_id: str,
    sensor_type: str,
) -> str:
    """Build the MQTT telemetry topic."""
    prefix = config["mqtt"]["topic_prefix"]
    return f"{prefix}/{zone_id}/{sensor_type}/telemetry"


# ---------------------------------------------------------------------------
# MQTT connection and local buffering
# ---------------------------------------------------------------------------

def create_mqtt_client(config: dict) -> mqtt.Client:
    """Create and connect the MQTT client."""
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

    client.connect(
        host=config["mqtt"]["host"],
        port=config["mqtt"]["port"],
        keepalive=config["mqtt"]["keepalive"],
    )

    client.loop_start()
    return client


def create_sensor_queues(
    zones: list[str],
    sensor_types: list[str],
) -> dict:
    """Create one local queue for each simulated sensor."""
    return {
        f"{zone_id}-{sensor_type}-01": deque()
        for zone_id in zones
        for sensor_type in sensor_types
    }


def dispatch_queued_messages(
    client: mqtt.Client,
    config: dict,
    sensor_queues: dict,
) -> int:
    """Publish all messages currently stored in local queues."""
    total_dispatched = 0

    for sensor_queue in sensor_queues.values():
        while sensor_queue:
            topic, payload = sensor_queue[0]

            result = client.publish(
                topic=topic,
                payload=payload,
                qos=config["mqtt"]["qos"],
            )

            result.wait_for_publish()
            sensor_queue.popleft()
            total_dispatched += 1

            # Do not log device IDs, topics or payload values loaded
            # from the external configuration file.
            logger.debug("Dispatched one queued sensor message.")

    return total_dispatched


# ---------------------------------------------------------------------------
# Main simulation loop
# ---------------------------------------------------------------------------

def run_simulation(config: dict) -> None:
    """Run the configured sensor simulation."""
    # Validate all run controls before creating messages or opening MQTT.
    simulation_config = config["simulation"]

    random.seed(simulation_config["random_seed"])

    number_of_samples = validate_reading_count(
        simulation_config["readings_per_sensor"]
    )

    # Store the validated value so generate_sensor_value uses it.
    simulation_config["readings_per_sensor"] = number_of_samples

    generation_interval = validate_interval(
        simulation_config["generation_interval_seconds"],
        "generation_interval_seconds",
    )

    dispatch_interval = validate_interval(
        simulation_config["dispatch_interval_seconds"],
        "dispatch_interval_seconds",
    )

    zones = config["zones"]
    sensor_types = list(config["sensor_profiles"])

    # Each simulated sensor gets its own bounded offline queue.
    sensor_queues = create_sensor_queues(
        zones=zones,
        sensor_types=sensor_types,
    )

    try:
        client = create_mqtt_client(config)
    except OSError as error:
        # logger.exception records the active exception and traceback.
        logger.exception("Failed to connect to the MQTT broker.")
        raise SystemExit(1) from error

    # Avoid logging raw values read from config.json.
    logger.info("Simulator configuration validated.")
    logger.info("Local sensor queues created.")

    time.sleep(1)
    logger.info("MQTT client connected: %s", client.is_connected())

    last_dispatch_time = time.monotonic()

    try:
        # The loop has a constant upper bound. The validated requested
        # number controls when execution stops.
        # Every cycle produces one reading for every zone/sensor pair.
        for sequence in range(1, MAX_READINGS_PER_SENSOR + 1):
            if sequence > number_of_samples:
                break

            logger.info("Generating sensor reading batch.")

            for zone_id in zones:
                for sensor_type in sensor_types:
                    device_id = f"{zone_id}-{sensor_type}-01"

                    topic = build_sensor_topic(
                        config=config,
                        zone_id=zone_id,
                        sensor_type=sensor_type,
                    )

                    message = build_sensor_message(
                        config=config,
                        zone_id=zone_id,
                        sensor_type=sensor_type,
                        sequence=sequence,
                    )

                    payload = json.dumps(message)
                    sensor_queues[device_id].append((topic, payload))

                    # Do not log sequence or device ID values derived
                    # from the external configuration.
                    logger.debug("Queued one sensor message.")

            logger.info("Waiting before the next generation cycle.")
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

        # Flush any readings still queued after the final generation cycle.
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
        logger.info("Simulation interrupted by user.")

    finally:
        client.loop_stop()
        client.disconnect()
        logger.info("MQTT client disconnected safely.")


if __name__ == "__main__":
    configuration = load_config()
    run_simulation(config=configuration)
