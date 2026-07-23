"""Tests for bounded telemetry event-ID deduplication."""

from uuid import uuid4

import pytest

from fog_app.processing.deduplication import EventIdDeduplicator


def test_records_new_event_and_detects_duplicate() -> None:
    """Return false for a new event and true when it appears again."""

    deduplicator = EventIdDeduplicator(max_size=10)
    event_id = uuid4()

    assert deduplicator.check_and_record(event_id) is False
    assert deduplicator.check_and_record(event_id) is True
    assert len(deduplicator) == 1


def test_evicts_oldest_event_when_cache_reaches_limit() -> None:
    """Remove the oldest event ID when the bounded cache becomes full."""

    deduplicator = EventIdDeduplicator(max_size=2)

    first_event_id = uuid4()
    second_event_id = uuid4()
    third_event_id = uuid4()

    assert deduplicator.check_and_record(first_event_id) is False
    assert deduplicator.check_and_record(second_event_id) is False
    assert deduplicator.check_and_record(third_event_id) is False

    assert len(deduplicator) == 2

    # The first ID was evicted, so it is treated as new again.
    assert deduplicator.check_and_record(first_event_id) is False


@pytest.mark.parametrize("invalid_size", [0, -1, -100])
def test_rejects_invalid_cache_size(invalid_size: int) -> None:
    """Reject cache sizes that cannot store any event IDs."""

    with pytest.raises(
        ValueError,
        match="Deduplication cache size must be at least 1",
    ):
        EventIdDeduplicator(max_size=invalid_size)