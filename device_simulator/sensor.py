"""Simple sensor simulator for FloodGuard Edge device."""
import json
import random
import time
from datetime import datetime, timezone
from pathlib import Path
import paho.mqtt.client as mqtt
from shared.telemetry import TelemetryMessage


CONFIG_PATH = Path(__file__).with_name("config.json")

def load_config() -> dict:
    """Load configuration from config.json file."""
    content = CONFIG_PATH.read_text(encoding="utf-8")
    return json.loads(content)

def generate_sensor_value(config: dict, sensor_type: str) -> float:
    """Generate a random sensor value based on the configuration and sensor type."""
    profile = config["sensor_profiles"][sensor_type]

    value = random.uniform(
        profile["min_value"], 
        profile["max_value"]
        )
    
    return round(value, 2)

def build_sensor_message(
        config: dict, zone_id: str, sensor_type: str, sequence: int,) -> dict:
    """Build a sensor message with the given configuration, zone ID, sensor type, and sequence number."""
    profile = config["sensor_profiles"][sensor_type]

    message = TelemetryMessage(
        device_id=f'{zone_id}-{sensor_type}-01',
        zone_id=zone_id,
        sensor_type=sensor_type,
        value=generate_sensor_value(config, sensor_type),
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
    print(f'Configured zones: {zones}')
    sensor_types = list(config['sensor_profiles'])
    print(f"Configured sensors: {sensor_types}")

    client = create_mqtt_client(config)
    time.sleep(1)  # Allow time for the MQTT client to connect
    print(f'MQTT client connected: {client.is_connected()}')

    for zone_id in zones:
        print(f'\nZone: {zone_id}')

        for sensor_type in sensor_types:
            topic = build_sensor_topic(
                config=config, 
                zone_id=zone_id, 
                sensor_type=sensor_type
        )

            print(f'\nMQTT topic: {topic}')


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

                print(f"Published message {number} to topic {topic}")
                time.sleep(interval)

    client.loop_stop()
    client.disconnect()

    print("Simulation completed. MQTT client disconnected.")