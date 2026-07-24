"""Reject stale timestamps and out-of-order device sequence numbers."""

from datetime import datetime, timezone


class MessageTimestampError(ValueError):
    """Raised when a timestamp cannot be safely compared."""


def is_stale_message(
    timestamp: datetime,
    maximum_age_seconds: float,
    *,
    now: datetime | None = None,
) -> bool:
    """Return whether a telemetry timestamp is older than the allowed age."""

    if maximum_age_seconds < 0:
        raise ValueError("Maximum message age cannot be negative.")

    # Tests can inject time; production uses the current UTC time.
    reference_time = now or datetime.now(timezone.utc)

    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise MessageTimestampError(
            "Telemetry timestamp must include timezone information."
        )

    if reference_time.tzinfo is None or reference_time.utcoffset() is None:
        raise MessageTimestampError(
            "Reference time must include timezone information."
        )

    timestamp_utc = timestamp.astimezone(timezone.utc)
    reference_time_utc = reference_time.astimezone(timezone.utc)

    age_seconds = (reference_time_utc - timestamp_utc).total_seconds()

    return age_seconds > maximum_age_seconds


class DeviceSequenceTracker:
    """Track the latest accepted sequence number independently per device."""

    def __init__(self) -> None:
        """Create an empty sequence tracker."""

        self._latest_sequences: dict[str, int] = {}

    def __len__(self) -> int:
        """Return the number of devices currently tracked."""

        return len(self._latest_sequences)

    def latest_for(self, device_id: str) -> int | None:
        """Return the latest accepted sequence for a device."""

        return self._latest_sequences.get(device_id)

    def check_and_record(self, device_id: str, sequence: int) -> bool:
        """Return whether a sequence is out of order and record valid progress.

        A sequence is out of order when it is equal to or lower than the
        latest accepted sequence for the same device.
        """

        if not device_id.strip():
            raise ValueError("Device ID cannot be empty.")

        if sequence < 1:
            raise ValueError("Sequence number must be at least 1.")

        # Sequence numbers increase independently for every device.
        latest_sequence = self._latest_sequences.get(device_id)

        if latest_sequence is not None and sequence <= latest_sequence:
            return True

        self._latest_sequences[device_id] = sequence
        return False