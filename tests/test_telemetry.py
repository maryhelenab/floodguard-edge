"""Test for shared telemetry module."""
import pytest
from pydantic import ValidationError
from datetime import datetime, timezone
from shared.telemetry import TelemetryMessage

def test_telemetry_message() -> None:
    """Test the TelemetryMessage model."""
    #Create a valid TelemetryMessage instance with sample data.
    message = TelemetryMessage(
        device_id="dublin-zone-01-rainfall-01",
        zone_id="dublin-zone-01",
        sensor_type="rainfall",
        value=5.12,
        unit="mm/h",
        sequence=1,
        timestamp=datetime.now(timezone.utc)
    )

    # Confirm that Pydantic preserves the data types and values correctly.
    assert message.sensor_type == "rainfall"
    assert message.value == 5.12
    assert message.sequence == 1
    assert message.event_id is not None  # Ensure that an event_id is generated

def test_invalid_sequence_is_rejected() -> None:
    """Test that an invalid sequence number raises a ValidationError."""
    with pytest.raises(ValidationError):
        TelemetryMessage(
            device_id="dublin-zone-01-rainfall-01",
            zone_id="dublin-zone-01",
            sensor_type="rainfall",
            value=5.12,
            unit="mm/h",
            sequence=-1,  # Invalid sequence number
            timestamp=datetime.now(timezone.utc)
        )

def test_event_id_are_unique() -> None:
    """Test that each TelemetryMessage instance has a unique event_id."""
    payload = {
        'device_id': "dublin-zone-01-rainfall-01",
        'zone_id': "dublin-zone-01",
        'sensor_type': "rainfall",
        'value': 5.12,
        'unit': "mm/h",
        'sequence': 1,
        'timestamp': datetime.now(timezone.utc)
    }

    first_message = TelemetryMessage(**payload)
    second_message = TelemetryMessage(**payload)

    assert first_message.event_id != second_message.event_id  # Ensure that event_ids are unique