"""AWS Lambda that provides the FloodGuard public API."""

import json
import logging
import os
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
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

ZONES = [
    "dublin-zone-01",
    "dublin-zone-02",
    "dublin-zone-03",
    "dublin-zone-04",
]

dynamodb = boto3.resource("dynamodb", config=DYNAMODB_CONFIG)
table = dynamodb.Table(TABLE_NAME)


def api_response(
    status_code: int,
    body: dict,
) -> dict:
    """Create a response for API Gateway."""

    return {
        "statusCode": status_code,
        "headers": {
            "content-type": "application/json",
            "access-control-allow-origin": "*",
        },
        "body": json.dumps(body),
    }


def prepare_item(
    item: dict,
) -> dict:
    """Prepare one DynamoDB item for the API response."""

    result = dict(item)

    if isinstance(
        result.get("timestamp_ms"),
        Decimal,
    ):
        result["timestamp_ms"] = int(
            result["timestamp_ms"]
        )

    payload_json = result.pop(
        "payload_json",
        "{}",
    )

    result["payload"] = json.loads(
        payload_json
    )

    return result


def query_events(
    zone_id: str,
    event_type: str,
    limit: int,
) -> list[dict]:
    """Return recent status or alert events."""

    response = table.query(
        KeyConditionExpression=(
            Key("pk").eq(
                f"ZONE#{zone_id}"
            )
            & Key("sk").begins_with(
                f"{event_type.upper()}#"
            )
        ),
        ScanIndexForward=False,
        Limit=limit,
    )

    return [
        prepare_item(item)
        for item in response.get("Items", [])
    ]


def read_limit(
    event: dict,
) -> int:
    """Read and validate the optional limit parameter."""

    query_parameters = (
        event.get("queryStringParameters")
        or {}
    )

    limit = int(
        query_parameters.get("limit", 20)
    )

    if limit < 1 or limit > 100:
        raise ValueError(
            "The limit must be between 1 and 100."
        )

    return limit


def lambda_handler(
    event: dict,
    context,
) -> dict:
    """Handle one request from API Gateway."""

    del context

    route_key = event.get(
        "routeKey",
        "",
    )

    try:
        if route_key == "GET /health":
            return api_response(
                200,
                {
                    "status": "healthy",
                    "service": "FloodGuard Query Lambda",
                    "table": TABLE_NAME,
                },
            )

        if route_key == "GET /zones":
            return api_response(
                200,
                {
                    "count": len(ZONES),
                    "zones": ZONES,
                },
            )

        path_parameters = (
            event.get("pathParameters")
            or {}
        )

        zone_id = path_parameters.get(
            "zone_id"
        )

        if not zone_id:
            return api_response(
                400,
                {
                    "detail": (
                        "The zone_id path parameter "
                        "is required."
                    )
                },
            )

        if zone_id not in ZONES:
            return api_response(
                404,
                {
                    "detail": (
                        f"Unknown zone: {zone_id}."
                    )
                },
            )

        if (
            route_key
            == "GET /zones/{zone_id}/latest"
        ):
            items = query_events(
                zone_id,
                event_type="status",
                limit=1,
            )

            if not items:
                return api_response(
                    404,
                    {
                        "detail": (
                            "No status data found for "
                            f"{zone_id}."
                        )
                    },
                )

            return api_response(
                200,
                items[0],
            )

        if (
            route_key
            == "GET /zones/{zone_id}/history"
        ):
            limit = read_limit(event)

            items = query_events(
                zone_id,
                event_type="status",
                limit=limit,
            )

            return api_response(
                200,
                {
                    "zone_id": zone_id,
                    "count": len(items),
                    "items": items,
                },
            )

        if (
            route_key
            == "GET /zones/{zone_id}/alerts"
        ):
            limit = read_limit(event)

            items = query_events(
                zone_id,
                event_type="alert",
                limit=limit,
            )

            return api_response(
                200,
                {
                    "zone_id": zone_id,
                    "count": len(items),
                    "items": items,
                },
            )

        return api_response(
            404,
            {
                "detail": (
                    f"Route not found: {route_key}"
                )
            },
        )

    except ValueError as error:
        return api_response(
            400,
            {
                "detail": str(error)
            },
        )

    except Exception:
        LOGGER.exception(
            "Unexpected query Lambda error."
        )

        return api_response(
            500,
            {
                "detail": "Internal server error."
            },
        )
