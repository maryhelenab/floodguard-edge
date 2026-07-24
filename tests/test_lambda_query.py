"""Tests for the query Lambda, using moto to mock DynamoDB."""

import json

from backend import lambda_query  # noqa: E402  (env vars must be set first)

TABLE_NAME = lambda_query.TABLE_NAME
ZONE_ID = "dublin-zone-01"

def api_gateway_event(
    route_key: str,
    zone_id: str | None = None,
    query: dict | None = None,
) -> dict:
    """Build a minimal API Gateway HTTP API v2 event."""

    event: dict = {"routeKey": route_key}

    if zone_id is not None:
        event["pathParameters"] = {"zone_id": zone_id}

    if query is not None:
        event["queryStringParameters"] = query

    return event

def status_item(timestamp_ms: int, event_id: str) -> dict:
    """Build one status item matching the storage schema."""

    return {
        "pk": f"ZONE#{ZONE_ID}",
        "sk": f"STATUS#{timestamp_ms}#{event_id}",
        "event_type": "status",
        "zone_id": ZONE_ID,
        "event_id": event_id,
        "event_time": "2026-07-24T10:00:00+00:00",
        "timestamp_ms": timestamp_ms,
        "received_at": "2026-07-24T10:00:01+00:00",
        "mqtt_topic": f"city/drainage/{ZONE_ID}/fog/status",
        "payload_json": json.dumps({"risk_level": "WARNING"}),
    }

def alert_item(timestamp_ms: int, event_id: str) -> dict:
    """Build one alert item matching the storage schema."""

    return {
        "pk": f"ZONE#{ZONE_ID}",
        "sk": f"ALERT#{timestamp_ms}#{event_id}",
        "event_type": "alert",
        "zone_id": ZONE_ID,
        "event_id": event_id,
        "event_time": "2026-07-24T10:05:00+00:00",
        "timestamp_ms": timestamp_ms,
        "received_at": "2026-07-24T10:05:01+00:00",
        "mqtt_topic": f"city/drainage/{ZONE_ID}/fog/alert",
        "payload_json": json.dumps({"severity": "CRITICAL"}),
    }

def body_of(response: dict) -> dict:
    """Parse the JSON body of a Lambda API Gateway response."""

    return json.loads(response["body"])

def test_health_route(dynamodb_table) -> None:
    response = lambda_query.lambda_handler(
        api_gateway_event("GET /health"),
        context=None,
    )

    assert response["statusCode"] == 200
    assert body_of(response)["status"] == "healthy"

def test_zones_route(dynamodb_table) -> None:
    response = lambda_query.lambda_handler(
        api_gateway_event("GET /zones"),
        context=None,
    )

    assert response["statusCode"] == 200
    assert body_of(response)["count"] == 4

def test_unknown_zone_returns_404(dynamodb_table) -> None:
    response = lambda_query.lambda_handler(
        api_gateway_event(
            "GET /zones/{zone_id}/latest",
            zone_id="not-a-real-zone",
        ),
        context=None,
    )

    assert response["statusCode"] == 404

def test_missing_zone_id_returns_400(dynamodb_table) -> None:
    response = lambda_query.lambda_handler(
        api_gateway_event("GET /zones/{zone_id}/latest"),
        context=None,
    )

    assert response["statusCode"] == 400

def test_latest_status_not_found_returns_404(
    dynamodb_table,
) -> None:
    response = lambda_query.lambda_handler(
        api_gateway_event(
            "GET /zones/{zone_id}/latest",
            zone_id=ZONE_ID,
        ),
        context=None,
    )

    assert response["statusCode"] == 404

def test_latest_status_returns_most_recent(
    dynamodb_table,
) -> None:
    dynamodb_table.put_item(
        Item=status_item(1000, "older-event")
    )
    dynamodb_table.put_item(
        Item=status_item(2000, "newer-event")
    )

    response = lambda_query.lambda_handler(
        api_gateway_event(
            "GET /zones/{zone_id}/latest",
            zone_id=ZONE_ID,
        ),
        context=None,
    )

    assert response["statusCode"] == 200
    body = body_of(response)
    assert body["event_id"] == "newer-event"
    assert body["payload"]["risk_level"] == "WARNING"

def test_history_returns_items_ordered_and_respects_limit(
    dynamodb_table,
) -> None:
    for i in range(5):
        dynamodb_table.put_item(
            Item=status_item(1000 + i, f"event-{i}")
        )

    response = lambda_query.lambda_handler(
        api_gateway_event(
            "GET /zones/{zone_id}/history",
            zone_id=ZONE_ID,
            query={"limit": "2"},
        ),
        context=None,
    )

    assert response["statusCode"] == 200
    body = body_of(response)
    assert body["count"] == 2
    # Newest first.
    assert body["items"][0]["event_id"] == "event-4"

def test_alerts_route_returns_only_alerts(
    dynamodb_table,
) -> None:
    dynamodb_table.put_item(
        Item=status_item(1000, "status-event")
    )
    dynamodb_table.put_item(
        Item=alert_item(2000, "alert-event")
    )

    response = lambda_query.lambda_handler(
        api_gateway_event(
            "GET /zones/{zone_id}/alerts",
            zone_id=ZONE_ID,
        ),
        context=None,
    )

    body = body_of(response)
    assert body["count"] == 1
    assert body["items"][0]["event_id"] == "alert-event"

def test_invalid_limit_returns_400(dynamodb_table) -> None:
    response = lambda_query.lambda_handler(
        api_gateway_event(
            "GET /zones/{zone_id}/history",
            zone_id=ZONE_ID,
            query={"limit": "500"},
        ),
        context=None,
    )

    assert response["statusCode"] == 400

def test_unknown_route_without_zone_returns_400(
    dynamodb_table,
) -> None:
    # Any route that isn't /health or /zones requires a zone_id
    # path parameter before the route itself is checked.
    response = lambda_query.lambda_handler(
        api_gateway_event("GET /not/a/real/route"),
        context=None,
    )

    assert response["statusCode"] == 400

def test_unknown_route_with_zone_returns_404(
    dynamodb_table,
) -> None:
    response = lambda_query.lambda_handler(
        api_gateway_event(
            "GET /zones/{zone_id}/not-a-real-action",
            zone_id=ZONE_ID,
        ),
        context=None,
    )

    assert response["statusCode"] == 404

def test_unexpected_error_returns_500(dynamodb_table) -> None:
    # A non-numeric, non-castable limit triggers a TypeError inside
    # read_limit rather than the ValueError path, exercising the
    # generic error handler.
    event = api_gateway_event(
        "GET /zones/{zone_id}/history",
        zone_id=ZONE_ID,
        query={"limit": ["not", "a", "number"]},
    )

    response = lambda_query.lambda_handler(event, context=None)

    assert response["statusCode"] == 500
    assert body_of(response)["detail"] == "Internal server error."

def test_response_includes_cors_header(dynamodb_table) -> None:

    response = lambda_query.lambda_handler(
        api_gateway_event("GET /health"),
        context=None,
    )

    assert (
        response["headers"]["access-control-allow-origin"] == "*"
    )
