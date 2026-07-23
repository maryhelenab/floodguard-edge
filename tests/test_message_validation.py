"""Tests for telemetry freshness and device-sequence validation."""

from datetime import datetime, timedelta, timezone

import pytest

from fog_app.processing.message_validation import (
    DeviceSequenceTracker,
    MessageTimestampError,
    is_stale_message,
)


def test_detects_stale_message_using_injected_time() -> None:
    """Detect telemetry older than the configured maximum age."""

    now = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
    timestamp = now - timedelta(seconds=61)

    assert (
        is_stale_message(
            timestamp,
            maximum_age_seconds=60,
            now=now,
        )
        is True
    )


def test_accepts_fresh_message() -> None:
    """Accept telemetry that remains inside the permitted age."""

    now = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
    timestamp = now - timedelta(seconds=30)

    assert (
        is_stale_message(
            timestamp,
            maximum_age_seconds=60,
            now=now,
        )
        is False
    )


def test_accepts_message_exactly_at_age_limit() -> None:
    """Accept telemetry whose age is exactly equal to the limit."""

    now = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
    timestamp = now - timedelta(seconds=60)

    assert (
        is_stale_message(
            timestamp,
            maximum_age_seconds=60,
            now=now,
        )
        is False
    )


def test_rejects_timestamp_without_timezone() -> None:
    """Reject timestamps that cannot be compared safely in UTC."""

    naive_timestamp = datetime(2026, 7, 23, 12, 0)
    aware_now = datetime(2026, 7, 23, 12, 1, tzinfo=timezone.utc)

    with pytest.raises(
        MessageTimestampError,
        match="Telemetry timestamp must include timezone",
    ):
        is_stale_message(
            naive_timestamp,
            maximum_age_seconds=60,
            now=aware_now,
        )


def test_accepts_increasing_device_sequences() -> None:
    """Record increasing sequences for the same device."""

    tracker = DeviceSequenceTracker()

    assert tracker.check_and_record("sensor-01", 1) is False
    assert tracker.check_and_record("sensor-01", 2) is False
    assert tracker.latest_for("sensor-01") == 2


def test_rejects_lower_sequence_without_replacing_latest() -> None:
    """Reject a lower sequence and preserve the latest accepted value."""

    tracker = DeviceSequenceTracker()

    tracker.check_and_record("sensor-01", 10)

    assert tracker.check_and_record("sensor-01", 9) is True
    assert tracker.latest_for("sensor-01") == 10


def test_rejects_repeated_sequence() -> None:
    """Reject the same sequence when received again for one device."""

    tracker = DeviceSequenceTracker()

    tracker.check_and_record("sensor-01", 5)

    assert tracker.check_and_record("sensor-01", 5) is True


def test_tracks_devices_independently() -> None:
    """Allow separate devices to maintain independent sequences."""

    tracker = DeviceSequenceTracker()

    assert tracker.check_and_record("sensor-01", 8) is False
    assert tracker.check_and_record("sensor-02", 1) is False
    assert tracker.latest_for("sensor-01") == 8
    assert tracker.latest_for("sensor-02") == 1
    assert len(tracker) == 2