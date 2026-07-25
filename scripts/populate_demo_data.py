"""Generate varied FloodGuard demo data through the real MQTT-to-AWS flow.

Expected final zone conditions:
    dublin-zone-01 -> NORMAL
    dublin-zone-02 -> WATCH
    dublin-zone-03 -> WARNING
    dublin-zone-04 -> HIGH

The script publishes one continuous sequence for every sensor device, so the
fog node does not reject later cycles as out of order.
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import boto3
import paho.mqtt.client as mqtt


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

DEVICE_CONFIG_PATH = PROJECT_ROOT / "device_simulator" / "config.json"

TABLE_NAME = "FloodGuardEvents"
AWS_REGION = "us-east-1"

# These scales are based on the project's own risk-engine test cases.
# They should produce four clearly different final risk levels.
ZONE_SCALES = {
    "dublin-zone-01": 0.10,  # NORMAL
    "dublin-zone-02": 0.35,  # WATCH
    "dublin-zone-03": 0.55,  # WARNING
    "dublin-zone-04": 0.75,  # HIGH
}

EXPECTED_LEVELS = {
    "dublin-zone-01": "NORMAL",
    "dublin-zone-02": "WATCH",
    "dublin-zone-03": "WARNING",
    "dublin-zone-04": "HIGH",
}

# Values used by the transparent fog risk model as 100% reference points.
REFERENCE_VALUES = {
    "rainfall": 75.0,
    "water_level": 80.0,
    "flow_rate": 30.0,
    "soil_saturation": 90.0,
    "drain_blockage": 80.0,
}

DEFAULT_UNITS = {
    "rainfall": "mm/h",
    "water_level": "cm",
    "flow_rate": "L/s",
    "soil_saturation": "%",
    "drain_blockage": "%",
}


def load_device_config() -> dict[str, Any]:
    """Read the existing simulator configuration without changing it."""
    return json.loads(DEVICE_CONFIG_PATH.read_text(encoding="utf-8"))


def check_mosquitto(host: str, port: int) -> None:
    """Confirm that the local MQTT broker accepts connections."""
    try:
        with socket.create_connection((host, port), timeout=3):
            print(f"[OK] Mosquitto is available at {host}:{port}.")
    except OSError as error:
        raise RuntimeError(
            "Mosquitto is not running.\n"
            "Open PowerShell as Administrator and run:\n"
            "Start-Service mosquitto"
        ) from error


def start_service(module_name: str) -> subprocess.Popen[str]:
    """Start one long-running project component."""
    print(f"[START] {module_name}")

    creation_flags = getattr(
        subprocess,
        "CREATE_NEW_PROCESS_GROUP",
        0,
    )

    return subprocess.Popen(
        [sys.executable, "-m", module_name],
        cwd=PROJECT_ROOT,
        text=True,
        creationflags=creation_flags,
    )


def stop_service(process: subprocess.Popen[str], name: str) -> None:
    """Stop only a process created by this script."""
    if process.poll() is not None:
        return

    print(f"[STOP] {name}")
    process.terminate()

    try:
        process.wait(timeout=7)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def create_mqtt_client(config: dict[str, Any]) -> mqtt.Client:
    """Create and connect the demo telemetry publisher."""
    mqtt_config = config["mqtt"]

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"floodguard-varied-demo-{uuid4().hex[:10]}",
    )

    client.connect(
        host=mqtt_config["host"],
        port=int(mqtt_config["port"]),
        keepalive=int(mqtt_config["keepalive"]),
    )
    client.loop_start()

    # Give the network loop time to complete the connection.
    for _ in range(30):
        if client.is_connected():
            return client
        time.sleep(0.1)

    client.loop_stop()
    raise RuntimeError("The demo publisher could not connect to Mosquitto.")


def sensor_unit(config: dict[str, Any], sensor_type: str) -> str:
    """Use the configured unit and fall back to the normal project unit."""
    profile = config.get("sensor_profiles", {}).get(sensor_type, {})
    return str(profile.get("unit", DEFAULT_UNITS[sensor_type]))


def sensor_value(
    zone_id: str,
    sensor_type: str,
    cycle: int,
    cycles: int,
    interval_seconds: float,
) -> float:
    """Create a deterministic value for one zone and sensor.

    Water level changes gradually so the calculated rise rate is realistic.
    Other values stay stable, making the final state easy to explain.
    """
    scale = ZONE_SCALES[zone_id]
    target = REFERENCE_VALUES[sensor_type] * scale

    if sensor_type != "water_level":
        return round(target, 2)

    # The risk tests use a 10 cm/min reference for water-rise rate.
    target_rise_cm_min = 10.0 * scale
    increase_per_cycle = target_rise_cm_min * interval_seconds / 60.0

    # End the final cycle at the scaled target water level.
    first_value = target - increase_per_cycle * (cycles - 1)
    value = first_value + increase_per_cycle * (cycle - 1)

    return round(max(value, 0.0), 2)


def publish_demo_data(
    config: dict[str, Any],
    cycles: int,
    interval_seconds: float,
) -> int:
    """Publish all four zone profiles using continuous sequences."""
    # Import after the project root has been placed on sys.path.
    from shared.telemetry import TelemetryMessage

    mqtt_config = config["mqtt"]
    topic_prefix = mqtt_config["topic_prefix"]
    qos = int(mqtt_config["qos"])

    sensor_types = list(REFERENCE_VALUES)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

    client = create_mqtt_client(config)
    published = 0

    try:
        print("\n========================================")
        print("PUBLISHING VARIED ZONE CONDITIONS")
        print("========================================")

        for cycle in range(1, cycles + 1):
            print(f"[CYCLE] {cycle}/{cycles}")

            for zone_id in ZONE_SCALES:
                for sensor_type in sensor_types:
                    # A unique device ID prevents sequence conflicts with
                    # sensor processes used in earlier demonstrations.
                    device_id = (
                        f"{zone_id}-{sensor_type}-demo-{run_id}"
                    )

                    message = TelemetryMessage(
                        device_id=device_id,
                        zone_id=zone_id,
                        sensor_type=sensor_type,
                        value=sensor_value(
                            zone_id=zone_id,
                            sensor_type=sensor_type,
                            cycle=cycle,
                            cycles=cycles,
                            interval_seconds=interval_seconds,
                        ),
                        unit=sensor_unit(config, sensor_type),
                        sequence=cycle,
                        timestamp=datetime.now(timezone.utc),
                    )

                    topic = (
                        f"{topic_prefix}/{zone_id}/"
                        f"{sensor_type}/telemetry"
                    )

                    result = client.publish(
                        topic=topic,
                        payload=message.model_dump_json(),
                        qos=qos,
                        retain=False,
                    )
                    result.wait_for_publish()

                    if result.rc != mqtt.MQTT_ERR_SUCCESS:
                        raise RuntimeError(
                            f"MQTT publish failed with code {result.rc}."
                        )

                    published += 1

            if cycle < cycles:
                time.sleep(interval_seconds)

        print(f"[MQTT] Published {published} valid telemetry messages.")
        return published

    finally:
        client.loop_stop()
        client.disconnect()


def get_dynamodb_count() -> int:
    """Count every item currently stored in DynamoDB."""
    client = boto3.client("dynamodb", region_name=AWS_REGION)

    total_count = 0
    scan_args: dict[str, Any] = {
        "TableName": TABLE_NAME,
        "Select": "COUNT",
    }

    while True:
        response = client.scan(**scan_args)
        total_count += int(response.get("Count", 0))

        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            return total_count

        scan_args["ExclusiveStartKey"] = last_key


def print_dynamodb_count(label: str) -> int | None:
    """Show the table count but do not fail only because AWS is unavailable."""
    try:
        count = get_dynamodb_count()
        print(f"[DYNAMODB] {label}: {count} items")
        return count
    except Exception as error:
        print(f"[WARNING] Could not read DynamoDB count: {error}")
        return None


def parse_arguments() -> argparse.Namespace:
    """Read safe command-line options."""
    parser = argparse.ArgumentParser(
        description=(
            "Generate NORMAL, WATCH, WARNING and HIGH demo zones "
            "through the complete FloodGuard pipeline."
        )
    )

    parser.add_argument(
        "--cycles",
        type=int,
        default=12,
        help="Number of continuous telemetry cycles (default: 12).",
    )

    parser.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="Seconds between cycles (default: 2).",
    )

    parser.add_argument(
        "--final-wait",
        type=int,
        default=25,
        help="Seconds for SQS, Lambda and DynamoDB processing.",
    )

    parser.add_argument(
        "--start-services",
        action="store_true",
        help="Start and stop the Fog Node and Cloud Bridge automatically.",
    )

    return parser.parse_args()


def validate_arguments(args: argparse.Namespace) -> None:
    """Reject unsafe or ineffective command-line values."""
    if not 5 <= args.cycles <= 60:
        raise ValueError("--cycles must be between 5 and 60.")

    if not 1.0 <= args.interval <= 10.0:
        raise ValueError("--interval must be between 1 and 10 seconds.")

    if not 5 <= args.final_wait <= 120:
        raise ValueError("--final-wait must be between 5 and 120 seconds.")


def main() -> int:
    """Run the corrected demo population workflow."""
    args = parse_arguments()
    started_processes: list[tuple[subprocess.Popen[str], str]] = []

    try:
        validate_arguments(args)

        if not DEVICE_CONFIG_PATH.exists():
            raise FileNotFoundError(
                f"Simulator configuration not found: {DEVICE_CONFIG_PATH}"
            )

        config = load_device_config()
        mqtt_config = config["mqtt"]

        check_mosquitto(
            str(mqtt_config["host"]),
            int(mqtt_config["port"]),
        )

        print_dynamodb_count("Before generation")

        if args.start_services:
            fog_process = start_service("fog_app.mqtt.fog_node")
            started_processes.append((fog_process, "Fog Node"))
            print("[WAIT] Waiting 4 seconds for the Fog Node...")
            time.sleep(4)

            bridge_process = start_service("backend.cloud_bridge")
            started_processes.append((bridge_process, "Cloud Bridge"))
            print("[WAIT] Waiting 6 seconds for the Cloud Bridge...")
            time.sleep(6)
        else:
            print(
                "[INFO] Using Fog Node and Cloud Bridge processes "
                "that are already running."
            )

        publish_demo_data(
            config=config,
            cycles=args.cycles,
            interval_seconds=args.interval,
        )

        print(
            f"\n[WAIT] Waiting {args.final_wait} seconds "
            "for cloud processing..."
        )
        time.sleep(args.final_wait)

        print_dynamodb_count("After generation")

        print("\n========================================")
        print("VARIED DEMO DATA COMPLETED")
        print("========================================")
        print("Expected latest dashboard conditions:")

        for zone_id, level in EXPECTED_LEVELS.items():
            print(f"- {zone_id}: {level}")

        print(
            "\nRefresh the dashboard after approximately 10 seconds. "
            "The exact scores are calculated by the Fog Node."
        )
        return 0

    except KeyboardInterrupt:
        print("\n[CANCELLED] Generation interrupted by the user.")
        return 1

    except Exception as error:
        print(f"\n[ERROR] {error}")
        return 1

    finally:
        for process, name in reversed(started_processes):
            stop_service(process, name)


if __name__ == "__main__":
    raise SystemExit(main())
