"""AWS Lambda that stores SQS fog events in DynamoDB.

SQS absorbs traffic spikes and retries failed records.  This Lambda validates the
event type, builds the DynamoDB keys, and reports only the failed records so
successful records are not processed again.
"""

import json
import logging
import os
from datetime import datetime

import boto3
from botocore.config import Config


# Short timeouts prevent a Lambda invocation from waiting too long for DynamoDB.
DYNAMODB_CONFIG = Config(
    connect_timeout=1,
    read_timeout=2,
    retries={
        "total_max_attempts": 2,
        "mode": "standard",
    },
)

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)

# The environment variable allows the same code to use a different table.
TABLE_NAME = os.environ.get(
    "DYNAMODB_TABLE_NAME",
    "FloodGuardEvents",
)

dynamodb = boto3.resource("dynamodb", config=DYNAMODB_CONFIG)
table = dynamodb.Table(TABLE_NAME)


def timestamp_to_milliseconds(timestamp: str) -> int:
    """Convert an ISO-8601 timestamp to an integer used in the sort key."""

    # Python expects +00:00, so the common Z suffix is normalised first.
    parsed_time = datetime.fromisoformat(
        timestamp.replace("Z", "+00:00")
    )

    return int(parsed_time.timestamp() * 1000)


def save_event(event: dict) -> None:
    """Transform and persist one status or alert event."""

    event_type = event["event_type"]
    payload = event["payload"]
    zone_id = payload["zone_id"]

    # Status and alert payloads use different identifier and time field names.
    if event_type == "status":
        event_id = payload["event_id"]
        event_time = payload["computed_at"]
    elif event_type == "alert":
        event_id = payload["alert_id"]
        event_time = payload["triggered_at"]
    else:
        raise ValueError(f"Unsupported event type: {event_type}")

    timestamp_ms = timestamp_to_milliseconds(event_time)

    # pk groups events by zone.  sk groups by type and sorts by event time.
    item = {
        "pk": f"ZONE#{zone_id}",
        "sk": (
            f"{event_type.upper()}#"
            f"{timestamp_ms}#"
            f"{event_id}"
        ),
        "event_type": event_type,
        "zone_id": zone_id,
        "event_id": event_id,
        "event_time": event_time,
        "timestamp_ms": timestamp_ms,
        "received_at": event["received_at"],
        "mqtt_topic": event["mqtt_topic"],
        # Store the complete payload as JSON while keeping query fields separate.
        "payload_json": json.dumps(payload),
    }

    table.put_item(Item=item)

    LOGGER.info(
        "Saved %s event for %s: %s",
        event_type,
        zone_id,
        event_id,
    )


def lambda_handler(event: dict, context) -> dict:
    """Process one SQS batch and return partial batch failures."""

    # AWS passes context automatically; this function does not need it.
    del context

    failed_messages = []

    for record in event.get("Records", []):
        message_id = record["messageId"]

        try:
            cloud_event = json.loads(record["body"])
            save_event(cloud_event)
        except Exception:
            LOGGER.exception(
                "Failed to process SQS message: %s",
                message_id,
            )

            # SQS retries only these message IDs when partial failures are enabled.
            failed_messages.append({"itemIdentifier": message_id})

    return {"batchItemFailures": failed_messages}
