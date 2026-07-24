"""FloodGuard backend scalability test.

Tests 100, 500 and 1,000 events through:
    Amazon SQS -> ingestion Lambda -> DynamoDB

Safe by default: without --send, it only validates events locally.
The script never deletes messages or database records.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

# The script is inside scripts/, so the parent folder is the project root.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.cloud_models import CloudEventEnvelope
from fog_app.models import DerivedMetrics, FogStatus, SampleCounts, SensorSnapshot

DEFAULT_VOLUMES = [100, 500, 1000]
DEFAULT_REGION = os.getenv("BACKEND_AWS_REGION", "us-east-1")
DEFAULT_QUEUE = "floodguard-events"
DEFAULT_TABLE = os.getenv("DYNAMODB_TABLE_NAME", "FloodGuardEvents")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_time(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


# 1. Create valid and unique FloodGuard events.
def create_event(run_id: str, number: int, base_time: datetime) -> CloudEventEnvelope:
    zone_id = f"benchmark-{run_id}"
    event_time = base_time + timedelta(microseconds=number)

    status = FogStatus(
        event_id=uuid4(),
        fog_node_id="fog-benchmark-node",
        zone_id=zone_id,
        risk_level="WATCH",
        risk_score=35.0,
        computed_at=event_time,
        window_seconds=60,
        sensor_snapshot=SensorSnapshot(
            rainfall=12.5,
            water_level=60.0,
            flow_rate=25.0,
            soil_saturation=70.0,
            drain_blockage=20.0,
        ),
        derived_metrics=DerivedMetrics(
            water_rise_cm_min=1.5,
            flow_utilisation_percent=50.0,
            drainage_stress_score=35.0,
        ),
        sample_counts=SampleCounts(
            rainfall=5,
            water_level=5,
            flow_rate=5,
            soil_saturation=5,
            drain_blockage=5,
        ),
        reasons=[f"Scalability benchmark event {number}"],
        missing_sensor_types=[],
        source_event_ids=[uuid4()],
    )

    envelope = CloudEventEnvelope(
        event_type="status",
        mqtt_topic=f"city/drainage/{zone_id}/fog/status",
        received_at=event_time,
        payload=status,
    )

    # Validate the exact JSON structure that will be placed in SQS.
    return CloudEventEnvelope.model_validate_json(envelope.model_dump_json())


def create_events(run_id: str, volume: int) -> list[CloudEventEnvelope]:
    base_time = utc_now()
    events = [create_event(run_id, number, base_time) for number in range(1, volume + 1)]

    # Unique IDs prevent the benchmark messages from being treated as duplicates.
    unique_ids = {str(event.payload.event_id) for event in events}
    if len(events) != volume or len(unique_ids) != volume:
        raise RuntimeError("Generated events are missing or not unique.")
    return events


# 2. Find and validate AWS resources.
def queue_url(sqs: Any, name: str, supplied_url: str | None) -> str:
    if supplied_url:
        return supplied_url
    return sqs.get_queue_url(QueueName=name)["QueueUrl"]


def dlq_url(sqs: Any, main_queue_url: str, supplied_url: str | None) -> str | None:
    if supplied_url:
        return supplied_url

    response = sqs.get_queue_attributes(
        QueueUrl=main_queue_url,
        AttributeNames=["RedrivePolicy"],
    )
    policy = response.get("Attributes", {}).get("RedrivePolicy")
    if not policy:
        return None

    arn = json.loads(policy).get("deadLetterTargetArn")
    if not arn:
        return None

    return sqs.get_queue_url(QueueName=arn.rsplit(":", 1)[-1])["QueueUrl"]


def queue_count(sqs: Any, url: str | None) -> int | None:
    """Return the approximate number of visible messages."""

    if not url:
        return None
    response = sqs.get_queue_attributes(
        QueueUrl=url,
        AttributeNames=["ApproximateNumberOfMessages"],
    )
    return int(response.get("Attributes", {}).get("ApproximateNumberOfMessages", "0"))


def validate_aws(session: boto3.Session, main_queue_url: str, table_name: str) -> None:
    identity = session.client("sts").get_caller_identity()
    session.client("sqs").get_queue_attributes(
        QueueUrl=main_queue_url,
        AttributeNames=["QueueArn"],
    )

    table = session.resource("dynamodb").Table(table_name)
    table.load()
    if table.table_status != "ACTIVE":
        raise RuntimeError(f"DynamoDB table is not ACTIVE: {table.table_status}")

    print("AWS account:", identity.get("Account"))
    print("AWS identity:", identity.get("Arn"))
    print("DynamoDB status:", table.table_status)


# 3. Send events and verify DynamoDB persistence.
def send_events(sqs: Any, main_queue_url: str, events: list[CloudEventEnvelope]) -> int:
    """Send events in batches of 10, the maximum allowed by SQS."""

    accepted = 0
    for start in range(0, len(events), 10):
        batch = events[start : start + 10]
        entries = [
            {
                "Id": f"event-{start + position}",
                "MessageBody": event.model_dump_json(),
            }
            for position, event in enumerate(batch, start=1)
        ]

        response = sqs.send_message_batch(QueueUrl=main_queue_url, Entries=entries)
        if response.get("Failed"):
            raise RuntimeError(f"SQS rejected messages: {response['Failed']}")
        accepted += len(response.get("Successful", []))

    return accepted


def count_records(table: Any, zone_id: str) -> int:
    """Count all records in the unique benchmark-zone partition."""

    query: dict[str, Any] = {
        "KeyConditionExpression": Key("pk").eq(f"ZONE#{zone_id}"),
        "Select": "COUNT",
        "ConsistentRead": True,
    }
    total = 0

    # DynamoDB can return more than one page, especially for 1,000 events.
    while True:
        response = table.query(**query)
        total += int(response.get("Count", 0))
        if not response.get("LastEvaluatedKey"):
            return total
        query["ExclusiveStartKey"] = response["LastEvaluatedKey"]


def wait_for_records(
    table: Any,
    zone_id: str,
    expected: int,
    timeout: float,
    interval: float,
) -> tuple[int, bool]:
    deadline = time.monotonic() + timeout

    while True:
        stored = count_records(table, zone_id)
        print(f"  DynamoDB: {stored}/{expected}", flush=True)
        if stored >= expected:
            return stored, False
        if time.monotonic() >= deadline:
            return stored, True
        time.sleep(interval)


# 4. Run one volume and calculate its metrics.
def run_test(
    sqs: Any,
    table: Any,
    main_queue_url: str,
    dead_letter_queue_url: str | None,
    volume: int,
    repetition: int,
    timeout: float,
    interval: float,
) -> dict[str, Any]:
    started = utc_now()
    run_id = f"aws-{volume}-r{repetition}-{started:%Y%m%dT%H%M%SZ}-{uuid4().hex[:6]}"
    zone_id = f"benchmark-{run_id}"

    print(f"\n=== {volume} events | run {repetition} ===")
    print("Run ID:", run_id)
    print("Zone:", zone_id)

    events = create_events(run_id, volume)
    if count_records(table, zone_id) != 0:
        raise RuntimeError("The benchmark partition is not empty.")

    dlq_before = queue_count(sqs, dead_letter_queue_url)
    total_start = time.perf_counter()
    send_start = time.perf_counter()
    sent = send_events(sqs, main_queue_url, events)
    send_seconds = time.perf_counter() - send_start

    stored, timed_out = wait_for_records(table, zone_id, volume, timeout, interval)
    total_seconds = time.perf_counter() - total_start

    dlq_after = queue_count(sqs, dead_letter_queue_url)
    dlq_increase = None
    if dlq_before is not None and dlq_after is not None:
        dlq_increase = max(dlq_after - dlq_before, 0)

    return {
        "run_id": run_id,
        "zone_id": zone_id,
        "volume": volume,
        "repetition": repetition,
        "sent": sent,
        "stored": stored,
        "failures": max(volume - stored, 0),
        "success_percent": round((stored / volume) * 100, 3),
        "send_seconds": round(send_seconds, 3),
        "total_seconds": round(total_seconds, 3),
        "send_throughput": round(sent / max(send_seconds, 0.000001), 3),
        "effective_throughput": round(stored / max(total_seconds, 0.000001), 3),
        "queue_remaining": queue_count(sqs, main_queue_url),
        "dlq_increase": dlq_increase,
        "timed_out": timed_out,
        "started_at_utc": iso_time(started),
        "finished_at_utc": iso_time(utc_now()),
    }


# 5. Save reproducible evidence for the report.
def save_results(results: list[dict[str, Any]], args: argparse.Namespace) -> None:
    results_dir = PROJECT_ROOT / "results"
    docs_dir = PROJECT_ROOT / "docs"
    results_dir.mkdir(exist_ok=True)
    docs_dir.mkdir(exist_ok=True)

    csv_path = results_dir / "scalability_results.csv"
    json_path = results_dir / "scalability_results.json"
    report_path = docs_dir / "scalability_test_results.md"

    with csv_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)

    metadata = {
        "generated_at_utc": iso_time(utc_now()),
        "region": args.region,
        "queue": args.queue_name,
        "table": args.table_name,
        "volumes": args.volumes,
        "repeat": args.repeat,
        "measured_path": "SQS -> ingestion Lambda -> DynamoDB",
    }
    json_path.write_text(
        json.dumps({"metadata": metadata, "results": results}, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# FloodGuard Backend Scalability Test Results",
        "",
        "## Methodology",
        "",
        "Valid FloodGuard status events were sent to SQS in batches of ten. Each run "
        "used a unique `benchmark-*` zone. DynamoDB was checked until all expected "
        "records appeared or the timeout expired.",
        "",
        "Measured path: **SQS → ingestion Lambda → DynamoDB**.",
        "",
        "## Results",
        "",
        "| Events | Run | Sent | Stored | Failures | Send time (s) | Total time (s) | "
        "Throughput (events/s) | Queue remaining | DLQ increase | Success |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for row in results:
        dlq = "N/A" if row["dlq_increase"] is None else row["dlq_increase"]
        lines.append(
            f"| {row['volume']} | {row['repetition']} | {row['sent']} | "
            f"{row['stored']} | {row['failures']} | {row['send_seconds']:.3f} | "
            f"{row['total_seconds']:.3f} | {row['effective_throughput']:.3f} | "
            f"{row['queue_remaining']} | {dlq} | {row['success_percent']:.3f}% |"
        )

    lines += [
        "",
        "## Limitations",
        "",
        "- The test measures the AWS backend from SQS, not the complete Sensor → MQTT → Fog path.",
        "- SQS and DLQ message counts are approximate AWS metrics.",
        "- P50, P95 and P99 per-event latency are not reported because DynamoDB does not "
        "store a precise ingestion-complete timestamp.",
        "- AWS Academy credentials and Lambda concurrency can affect repeated results.",
        "",
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")

    print("\nSaved:")
    print("-", csv_path.relative_to(PROJECT_ROOT))
    print("-", json_path.relative_to(PROJECT_ROOT))
    print("-", report_path.relative_to(PROJECT_ROOT))


# 6. Read options and start the program.
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FloodGuard backend scalability test")
    parser.add_argument("--send", action="store_true", help="Send events to AWS")
    parser.add_argument("--volumes", type=int, nargs="+", default=DEFAULT_VOLUMES)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument("--queue-name", default=DEFAULT_QUEUE)
    parser.add_argument("--queue-url", default=os.getenv("BACKEND_SQS_QUEUE_URL"))
    parser.add_argument("--dlq-url", default=os.getenv("BACKEND_SQS_DLQ_URL"))
    parser.add_argument("--table-name", default=DEFAULT_TABLE)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--interval", type=float, default=2.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if any(volume <= 0 for volume in args.volumes) or args.repeat <= 0:
        raise SystemExit("Volumes and repeat must be greater than zero.")
    if args.timeout <= 0 or args.interval <= 0:
        raise SystemExit("Timeout and interval must be greater than zero.")

    # Dry-run: validates every event without contacting AWS.
    if not args.send:
        print("DRY-RUN: no data will be sent to AWS.\n")
        for volume in args.volumes:
            for repetition in range(1, args.repeat + 1):
                run_id = f"local-{volume}-r{repetition}-{uuid4().hex[:6]}"
                events = create_events(run_id, volume)
                print(f"Validated {len(events)} unique events (run {repetition}).")
        print("\nLOCAL VALIDATION COMPLETED SUCCESSFULLY.")
        return

    results: list[dict[str, Any]] = []
    try:
        session = boto3.Session(region_name=args.region)
        sqs = session.client("sqs")
        table = session.resource("dynamodb").Table(args.table_name)
        main_queue_url = queue_url(sqs, args.queue_name, args.queue_url)
        dead_letter_queue_url = dlq_url(sqs, main_queue_url, args.dlq_url)

        validate_aws(session, main_queue_url, args.table_name)
        print("\nNo existing data will be deleted.")
        print("SQS:", main_queue_url)
        print("DLQ:", dead_letter_queue_url or "Not configured or not discovered")
        print("Table:", args.table_name)

        for volume in args.volumes:
            for repetition in range(1, args.repeat + 1):
                result = run_test(
                    sqs,
                    table,
                    main_queue_url,
                    dead_letter_queue_url,
                    volume,
                    repetition,
                    args.timeout,
                    args.interval,
                )
                results.append(result)
                print(
                    f"Result: stored={result['stored']}, failures={result['failures']}, "
                    f"time={result['total_seconds']}s, "
                    f"throughput={result['effective_throughput']} events/s"
                )

    except (NoCredentialsError, BotoCoreError, ClientError) as error:
        raise SystemExit(f"AWS ERROR: {error}") from error
    except KeyboardInterrupt:
        print("\nInterrupted. Completed runs will still be saved.")

    if not results:
        raise SystemExit("No benchmark results were produced.")

    save_results(results, args)

    incomplete = [
        row
        for row in results
        if row["timed_out"]
        or row["stored"] < row["volume"]
        or (row["dlq_increase"] or 0) > 0
    ]
    if incomplete:
        raise SystemExit(f"Benchmark finished with {len(incomplete)} incomplete run(s).")

    print("\nBENCHMARK COMPLETED SUCCESSFULLY.")


if __name__ == "__main__":
    main()
