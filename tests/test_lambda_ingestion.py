"""Tests for the ingestion Lambda, using moto to mock DynamoDB."""

import json

import pytest

from backend import lambda_ingestion  # noqa: E402  (env vars must be set first)

TABLE_NAME = lambda_ingestion.TABLE_NAME

STATUS_PAYLOAD = {
    "event_id": "11111111-1111-1111-1111-111111111111",
    "zone_id": "dublin-zone-01",
    "computed_at": "2026-07-24T10:00:00+00:00",
}

ALERT_PAYLOAD = {
    "alert_id": "22222222-2222-2222-2222-222222222222",
    "zone_id": "dublin-zone-01",
    "triggered_at": "2026-07-24T10:05:00+00:00",
}

def make_sqs_record(message_id: str, body: dict) -> dict:
    """Build one fake SQS record for the Lambda event."""

    return {
        "messageId": message_id,
        "body": json.dumps(body),
    }

def status_event() -> dict:
    """Build one valid status cloud event."""

    return {
        "event_type": "status",
        "mqtt_topic": "city/drainage/dublin-zone-01/fog/status",
        "received_at": "2026-07-24T10:00:01+00:00",
        "payload": STATUS_PAYLOAD,
    }

def alert_event() -> dict:
    """Build one valid alert cloud event."""

    return {
        "event_type": "alert",
        "mqtt_topic": "city/drainage/dublin-zone-01/fog/alert",
        "received_at": "2026-07-24T10:05:01+00:00",
        "payload": ALERT_PAYLOAD,
    }

def test_timestamp_to_milliseconds_parses_iso() -> None:
    result = lambda_ingestion.timestamp_to_milliseconds(
        "2026-07-24T10:00:00+00:00"
    )

    assert isinstance(result, int)
    assert result > 0

def test_timestamp_to_milliseconds_handles_z_suffix() -> None:
    with_z = lambda_ingestion.timestamp_to_milliseconds(
        "2026-07-24T10:00:00Z"
    )
    with_offset = lambda_ingestion.timestamp_to_milliseconds(
        "2026-07-24T10:00:00+00:00"
    )

    assert with_z == with_offset

def test_save_event_writes_status_item(dynamodb_table) -> None:
    lambda_ingestion.save_event(status_event())

    timestamp_ms = lambda_ingestion.timestamp_to_milliseconds(
        STATUS_PAYLOAD["computed_at"]
    )

    stored = dynamodb_table.get_item(
        Key={
            "pk": "ZONE#dublin-zone-01",
            "sk": f"STATUS#{timestamp_ms}#{STATUS_PAYLOAD['event_id']}",
        }
    )

    assert "Item" in stored
    assert stored["Item"]["event_type"] == "status"
    assert stored["Item"]["zone_id"] == "dublin-zone-01"

def test_save_event_writes_alert_item(dynamodb_table) -> None:
    lambda_ingestion.save_event(alert_event())

    response = dynamodb_table.scan()
    items = response["Items"]

    assert len(items) == 1
    assert items[0]["event_type"] == "alert"
    assert items[0]["event_id"] == ALERT_PAYLOAD["alert_id"]

def test_save_event_rejects_unsupported_type(dynamodb_table) -> None:
    bad_event = status_event()
    bad_event["event_type"] = "unknown"

    with pytest.raises(ValueError, match="Unsupported event type"):
        lambda_ingestion.save_event(bad_event)

def test_lambda_handler_saves_all_valid_messages(
    dynamodb_table,
) -> None:
    event = {
        "Records": [
            make_sqs_record("msg-1", status_event()),
            make_sqs_record("msg-2", alert_event()),
        ]
    }

    result = lambda_ingestion.lambda_handler(event, context=None)

    assert result == {"batchItemFailures": []}
    assert dynamodb_table.scan()["Count"] == 2

def test_lambda_handler_reports_partial_failure(
    dynamodb_table,
) -> None:
    malformed_record = {
        "messageId": "msg-bad",
        "body": "{not valid json",
    }

    event = {
        "Records": [
            make_sqs_record("msg-good", status_event()),
            malformed_record,
        ]
    }

    result = lambda_ingestion.lambda_handler(event, context=None)

    assert result == {
        "batchItemFailures": [{"itemIdentifier": "msg-bad"}]
    }
    assert dynamodb_table.scan()["Count"] == 1

def test_lambda_handler_handles_empty_records(dynamodb_table) -> None:
    result = lambda_ingestion.lambda_handler({}, context=None)

    assert result == {"batchItemFailures": []}
