"""Persist fog status and alert outputs in a small local SQLite database.

Local storage preserves decisions when the cloud connection is unavailable.
A database error is logged and returned as ``False`` so monitoring continues.
"""

import logging
import sqlite3
from pathlib import Path

from fog_app.models import FogAlert, FogStatus


LOGGER = logging.getLogger(__name__)


# Repository class that hides SQL details from the processor.
class FogEventStore:
    """Store complete fog-node outputs in a local SQLite database."""

    def __init__(self, database_path: str | Path) -> None:
        """Prepare the database path and create the required tables."""

        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._create_tables()

    def _connect(self) -> sqlite3.Connection:
        """Open a short-lived SQLite connection."""

        # Short-lived connections keep this small repository simple.
        return sqlite3.connect(self.database_path)

    def _create_tables(self) -> None:
        """Create the required tables when they do not exist."""

        # Statuses and alerts are separated because they have different fields.
        schema = """
        CREATE TABLE IF NOT EXISTS processed_statuses (
            event_id TEXT PRIMARY KEY,
            zone_id TEXT NOT NULL,
            risk_level TEXT NOT NULL,
            risk_score REAL,
            timestamp TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS alerts (
            alert_id TEXT PRIMARY KEY,
            zone_id TEXT NOT NULL,
            severity TEXT NOT NULL,
            risk_score REAL NOT NULL,
            timestamp TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );
        """

        # IF NOT EXISTS makes startup safe for new and existing databases.
        with self._connect() as connection:
            connection.executescript(schema)

    def persist_status(self, status: FogStatus) -> bool:
        """Persist one processed status without crashing the fog node."""

        try:
            # Keep searchable columns plus the complete serialised output.
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO processed_statuses (
                        event_id,
                        zone_id,
                        risk_level,
                        risk_score,
                        timestamp,
                        payload_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(status.event_id),
                        status.zone_id,
                        status.risk_level,
                        status.risk_score,
                        status.computed_at.isoformat(),
                        status.model_dump_json(),
                    ),
                )

            return True

        except sqlite3.Error:
            LOGGER.exception(
                "Failed to persist status %s.",
                status.event_id,
            )
            return False

    def persist_alert(self, alert: FogAlert) -> bool:
        """Persist one alert without crashing the fog node."""

        try:
            # The alert ID is the primary key, preventing accidental duplicates.
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO alerts (
                        alert_id,
                        zone_id,
                        severity,
                        risk_score,
                        timestamp,
                        payload_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(alert.alert_id),
                        alert.zone_id,
                        alert.severity,
                        alert.risk_score,
                        alert.triggered_at.isoformat(),
                        alert.model_dump_json(),
                    ),
                )

            return True

        except sqlite3.Error:
            LOGGER.exception(
                "Failed to persist alert %s.",
                alert.alert_id,
            )
            return False

    def count_statuses(self) -> int:
        """Return the number of stored status rows."""

        with self._connect() as connection:
            result = connection.execute(
                "SELECT COUNT(*) FROM processed_statuses"
            ).fetchone()

        return int(result[0])

    def count_alerts(self) -> int:
        """Return the number of stored alert rows."""

        with self._connect() as connection:
            result = connection.execute(
                "SELECT COUNT(*) FROM alerts"
            ).fetchone()

        return int(result[0])
