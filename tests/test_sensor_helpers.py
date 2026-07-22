"""tests for sensor simulator helpers functions."""
from collections import deque
from unittest.mock import Mock
from device_simulator.sensor import(
    build_sensor_message,
    build_sensor_topic,
    dispatch_queued_messages,
    load_config,
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