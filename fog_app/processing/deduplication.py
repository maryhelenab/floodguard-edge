"""Detect duplicate telemetry IDs with a bounded in-memory cache."""

from collections import OrderedDict
from uuid import UUID


# OrderedDict provides fast lookup and remembers insertion order for eviction.
class EventIdDeduplicator:
    """Deduplicate telemetry messages based on their event IDs.

    This class maintains a bounded set of recently seen event IDs to prevent
    processing duplicate telemetry messages. It uses an OrderedDict to keep
    track of the order in which event IDs were added, allowing for efficient
    removal of the oldest entries when the maximum size is exceeded.
    """

    def __init__(self, max_size: int) -> None:
        """Create a deduplicator with a fixed maximum number of event IDs."""

        if max_size <= 1:
            raise ValueError("Deduplication cache size must be at least 1.")

        self.max_size = max_size
        self._event_ids: OrderedDict[UUID, None] = OrderedDict()

    def __len__(self) -> int:
        """Return the number of unique event IDs currently stored."""
        return len(self._event_ids)

    def check_and_record(self, event_id: UUID) -> bool:
        """Return whether an event is duplicated and record new event IDs.

        Returns:
            True when the event ID has already been processed.
            False when the event ID is new and has now been recorded.
        """

        # True means MQTT delivered an event that was already processed.
        if event_id in self._event_ids:
            return True

        self._event_ids[event_id] = None

        # Remove the oldest ID so memory use stays bounded.
        if len(self._event_ids) > self.max_size:
            self._event_ids.popitem(last=False)

        return False