"""AWS Lambda that exposes stored FloodGuard events through HTTP API routes."""

import json
import logging
import os
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from botocore.config import Config


# Keep calls short because API Gateway clients are waiting for a response.
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

# These are the zones currently supported by the simulator and dashboard.
ZONES = [
    "dublin-zone-01",
    "dublin-zone-02",
    "dublin-zone-03",
    "dublin-zone-04",
]

dynamodb = boto3.resource("dynamodb", config=DYNAMODB_CONFIG)
table = dynamodb.Table(TABLE_NAME)


def api_response(status_code: int, body: dict) -> dict:
    """Build the response format expected by API Gateway HTTP APIs."""

    return {
        "statusCode": status_code,
        "headers": {
            "content-type": "application/json",
            # The static dashboard is hosted on a different origin.
            "access-control-allow-origin": "*",
        },
        "body": json.dumps(body),
    }


def prepare_item(item: dict) -> dict:
    """Convert DynamoDB-specific values into browser-friendly JSON values."""

    # Work on a copy so the object returned by boto3 is not changed in place.
    result = dict(item)

    # DynamoDB represents numbers as Decimal, which json.dumps cannot encode.
    if isinstance(result.get("timestamp_ms"), Decimal):
        result["timestamp_ms"] = int(result["timestamp_ms"])

    # Restore the complete original fog payload as a nested JSON object.
    payload_json = result.pop("payload_json", "{}")
    result["payload"] = json.loads(payload_json)

    return result


def query_events(
    zone_id: str,
    event_type: str,
    limit: int,
) -> list[dict]:
    """Query the newest status or alert records for one zone."""

    response = table.query(
        # pk selects one zone; the sk prefix selects status or alert records.
        KeyConditionExpression=(
            Key("pk").eq(f"ZONE#{zone_id}")
            & Key("sk").begins_with(f"{event_type.upper()}#")
        ),
        # Descending order returns newest events first.
        ScanIndexForward=False,
        Limit=limit,
    )

    return [
        prepare_item(item)
        for item in response.get("Items", [])
    ]


def read_limit(event: dict) -> int:
    """Read and validate the optional ``?limit=`` query parameter."""

    query_parameters = event.get("queryStringParameters") or {}
    limit = int(query_parameters.get("limit", 20))

    # A fixed upper bound protects DynamoDB and keeps API responses manageable.
    if limit < 1 or limit > 100:
        raise ValueError("The limit must be between 1 and 100.")

    return limit


def lambda_handler(event: dict, context) -> dict:
    """Route one API Gateway request to the correct query operation."""

    del context
    route_key = event.get("routeKey", "")

    try:
        # Health does not query DynamoDB and can be used by deployment checks.
        if route_key == "GET /health":
            return api_response(
                200,
                {
                    "status": "healthy",
                    "service": "FloodGuard Query Lambda",
                    "table": TABLE_NAME,
                },
            )

        # The dashboard uses this route to discover supported zones.
        if route_key == "GET /zones":
            return api_response(
                200,
                {
                    "count": len(ZONES),
                    "zones": ZONES,
                },
            )

        path_parameters = event.get("pathParameters") or {}
        zone_id = path_parameters.get("zone_id")

        if not zone_id:
            return api_response(
                400,
                {"detail": "The zone_id path parameter is required."},
            )

        if zone_id not in ZONES:
            return api_response(
                404,
                {"detail": f"Unknown zone: {zone_id}."},
            )

        # Latest returns only the newest status record for the selected zone.
        if route_key == "GET /zones/{zone_id}/latest":
            items = query_events(
                zone_id,
                event_type="status",
                limit=1,
            )

            if not items:
                return api_response(
                    404,
                    {"detail": f"No status data found for {zone_id}."},
                )

            return api_response(200, items[0])

        # History returns recent status snapshots for dashboard charts.
        if route_key == "GET /zones/{zone_id}/history":
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

        # Alerts are queried separately from routine status snapshots.
        if route_key == "GET /zones/{zone_id}/alerts":
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
            {"detail": f"Route not found: {route_key}"},
        )

    # Invalid query parameters are client errors rather than server failures.
    except ValueError as error:
        return api_response(400, {"detail": str(error)})

    # Hide internal details from clients but keep the full traceback in logs.
    except Exception:
        LOGGER.exception("Unexpected query Lambda error.")
        return api_response(
            500,
            {"detail": "Internal server error."},
        )
