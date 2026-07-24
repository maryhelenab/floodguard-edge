"""AWS Lambda that saves SQS fog events in DynamoDB."""

import json
import logging
import os
from datetime import datetime

import boto3
from botocore.config import Config

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

TABLE_NAME = os.environ.get(
    "DYNAMODB_TABLE_NAME",
    "FloodGuardEvents",
)

dynamodb = boto3.resource("dynamodb", config=DYNAMODB_CONFIG)
table = dynamodb.Table(TABLE_NAME)


def timestamp_to_milliseconds(
    timestamp: str,
) -> int:
    """Convert an ISO timestamp into milliseconds."""

    parsed_time = datetime.fromisoformat(
        timestamp.replace("Z", "+00:00")
    )

    return int(
        parsed_time.timestamp() * 1000
    )


def save_event(
    event: dict,
) -> None:
    """Save one fog status or alert in DynamoDB."""

    event_type = event["event_type"]
    payload = event["payload"]

    zone_id = payload["zone_id"]

    if event_type == "status":
        event_id = payload["event_id"]
        event_time = payload["computed_at"]

    elif event_type == "alert":
        event_id = payload["alert_id"]
        event_time = payload["triggered_at"]

    else:
        raise ValueError(
            f"Unsupported event type: {event_type}"
        )

    timestamp_ms = timestamp_to_milliseconds(
        event_time
    )

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
        "payload_json": json.dumps(payload),
    }

    table.put_item(
        Item=item
    )

    LOGGER.info(
        "Saved %s event for %s: %s",
        event_type,
        zone_id,
        event_id,
    )


def lambda_handler(
    event: dict,
    context,
) -> dict:
    """Process a batch of messages received from SQS."""

    del context

    failed_messages = []

    for record in event.get("Records", []):
        message_id = record["messageId"]

        try:
            cloud_event = json.loads(
                record["body"]
            )

            save_event(
                cloud_event
            )

        except Exception:
            LOGGER.exception(
                "Failed to process SQS message: %s",
                message_id,
            )

            failed_messages.append(
                {
                    "itemIdentifier": message_id
                }
            )

    return {
        "batchItemFailures": failed_messages
    }
