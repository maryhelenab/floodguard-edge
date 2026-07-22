"""tests for sensor simulator helpers functions."""
from collections import deque
from unittest.mock import Mock, patch
from device_simulator.sensor import(
    build_sensor_message,
    build_sensor_topic,
    dispatch_queued_messages,
    load_config,
    create_sensor_queues,
    run_simulation,
)

def test_build_sensor_topic() -> None:
    """The MQTT topic should include the zone and sensor type."""
    config = load_config()

    topic = build_sensor_topic(
        config=config,
        zone_id="dublin-zone-01",
        sensor_type="rainfall"
    )

    assert topic == "city/drainage/dublin-zone-01/rainfall/telemetry"

def test_build_sensor_message() -> None:
    """The sensor message should include the correct fields."""
    config = load_config()

    message = build_sensor_message(
        config=config,
        zone_id="dublin-zone-01",
        sensor_type="rainfall",
        sequence=1
    )

    assert message['device_id'] == "dublin-zone-01-rainfall-01"
    assert message['zone_id'] == "dublin-zone-01"
    assert message['sensor_type'] == "rainfall"
    assert message['unit'] == "mm/h"
    assert message['sequence'] == 1
    assert message['event_id'] is not None  # Ensure that an event_id is generated

def test_dispatch_queued_messages() -> None:
    """Queued messages should be published and removed after confirmation."""
    config = load_config()

    publisher_result = Mock()
    client = Mock()
    client.publish.return_value = publisher_result

    topic =  'city/drainage/dublin-zone-01/rainfall/telemetry'
    payload = '{"sequence": 1}'

    sensor_queues = {
        'dublin-zone-01-rainfall-01': deque(
            [(topic, payload)]
        )
    }

    dispatch_count = dispatch_queued_messages(
        client=client,
        config=config,
        sensor_queues=sensor_queues
    )

    assert dispatch_count == 1
    assert len(sensor_queues['dublin-zone-01-rainfall-01']) == 0  # Ensure the queue is empty after dispatch
    client.publish.assert_called_once_with(
        topic=topic, 
        payload=payload,
        qos=config['mqtt']['qos'],
    )  # Ensure publish was called with correct parameters

    # Ensure wait_for_publish was called to confirm delivery
    publisher_result.wait_for_publish.assert_called_once_with()

def test_create_sensor_queues() -> None:
    """The sensor queues should be created for each zone and sensor type."""
    zones = ["dublin-zone-01", "dublin-zone-02"]
    sensor_types = ["rainfall", "water-level"]

    sensor_queues = create_sensor_queues(zones=zones, sensor_types=sensor_types)

    assert len(sensor_queues) == 4  # 2 zones * 2 sensor types
    assert 'dublin-zone-01-rainfall-01' in sensor_queues
    assert 'dublin-zone-02-water-level-01' in sensor_queues
    assert all(len(queue) == 0 for queue in sensor_queues.values())  # Ensure all queues are empty.

def test_run_simulation() -> None:
    """The simulation should run without errors and dispatch messages."""
    config = load_config()

    config["zones"] = ["dublin-zone-01"]
    config["sensor_profiles"] = {"rainfall": config["sensor_profiles"]["rainfall"]}
    config["simulation"]["readings_per_sensor"] = 2
    config["simulation"]["generation_interval_seconds"] = 0
    config["simulation"]["dispatch_interval_seconds"] = 999

    mock_client = Mock()
    mock_client.is_connected.return_value = True

    with patch(
        "device_simulator.sensor.create_mqtt_client",
        return_value=mock_client,
    ), patch(
        "device_simulator.sensor.time.sleep",
    ):
        run_simulation(config)

    assert mock_client.publish.call_count == 2  # Ensure two messages were published
    mock_client.loop_stop.assert_called_once()  # Ensure the MQTT loop was stopped
    mock_client.disconnect.assert_called_once()  # Ensure the MQTT client was disconnected