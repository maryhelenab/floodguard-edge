"""Controlled scalability test for the FloodGuard backend.

The script always creates and validates events locally first.
Messages are sent to Amazon SQS only when --send is provided.
"""

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import boto3


# -------------------------------------------------------------------
# Project imports
# -------------------------------------------------------------------

# When this file is executed directly, Python starts inside the
# scripts folder. Adding the project root allows imports such as
# backend.cloud_models and fog_app.models to work correctly.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.cloud_models import CloudEventEnvelope
from backend.config import BackendSettings
from fog_app.models import (
    DerivedMetrics,
    FogStatus,
    SampleCounts,
    SensorSnapshot,
)


# -------------------------------------------------------------------
# 1. Create valid benchmark events
# -------------------------------------------------------------------

def build_status_event(
    run_id: str,
    event_number: int,
) -> CloudEventEnvelope:
    """Create one valid and unique FloodGuard status event."""

    # Each event receives its own timestamp.
    # This helps prevent DynamoDB sort-key collisions later.
    now = datetime.now(timezone.utc)

    # The current FogStatus model does not have a test_run_id field.
    # The benchmark run is therefore identified through the zone_id.
    # This keeps benchmark data separate from the real Dublin zones.
    zone_id = f"benchmark-{run_id}"

    # UUID values ensure that every benchmark event is unique.
    event_id = uuid4()
    source_event_id = uuid4()

    status = FogStatus(
        event_id=event_id,
        fog_node_id="fog-benchmark-node",
        zone_id=zone_id,
        risk_level="WATCH",
        risk_score=35.0,
        computed_at=now,
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
        reasons=[
            f"Controlled scalability benchmark event {event_number}"
        ],
        missing_sensor_types=[],
        source_event_ids=[source_event_id],
    )

    # The envelope uses the same structure produced by the cloud bridge.
    return CloudEventEnvelope(
        event_type="status",
        mqtt_topic=f"city/drainage/{zone_id}/fog/status",
        received_at=now,
        payload=status,
    )


def create_events(
    run_id: str,
    volume: int,
) -> list[CloudEventEnvelope]:
    """Generate and validate all events for one benchmark run."""

    events = []

    for event_number in range(1, volume + 1):
        event = build_status_event(
            run_id=run_id,
            event_number=event_number,
        )

        # Serialize and validate the final JSON again.
        # This checks the exact message format that will later be sent
        # to Amazon SQS, rather than validating only the Python object.
        message_body = event.model_dump_json()

        validated_event = CloudEventEnvelope.model_validate_json(
            message_body
        )

        events.append(validated_event)

    return events


# -------------------------------------------------------------------
# 2. Send validated events to Amazon SQS
# -------------------------------------------------------------------

def send_events_to_sqs(
    sqs_client,
    queue_url: str,
    events: list[CloudEventEnvelope],
) -> int:
    """Send events in SQS batches and return the successful total."""

    successful_total = 0
    maximum_batch_size = 10

    for batch_start in range(
        0,
        len(events),
        maximum_batch_size,
    ):
        batch = events[
            batch_start:batch_start + maximum_batch_size
        ]

        entries = []

        for batch_position, event in enumerate(batch, start=1):
            event_number = batch_start + batch_position

            entries.append(
                {
                    "Id": f"event-{event_number}",
                    "MessageBody": event.model_dump_json(),
                }
            )

        response = sqs_client.send_message_batch(
            QueueUrl=queue_url,
            Entries=entries,
        )

        failed_entries = response.get("Failed", [])

        if failed_entries:
            raise RuntimeError(
                f"SQS failed to accept messages: {failed_entries}"
            )

        successful_total += len(
            response.get("Successful", [])
        )

    return successful_total


# -------------------------------------------------------------------
# 3. Read command-line options
# -------------------------------------------------------------------

def parse_arguments() -> argparse.Namespace:
    """Read the requested volume and execution mode."""

    parser = argparse.ArgumentParser(
        description=(
            "Generate and optionally send FloodGuard benchmark events."
        )
    )

    parser.add_argument(
        "--volume",
        type=int,
        default=10,
        help="Number of benchmark events to generate.",
    )

    parser.add_argument(
        "--send",
        action="store_true",
        help="Send the validated events to Amazon SQS.",
    )

    return parser.parse_args()


# -------------------------------------------------------------------
# 4. Run the benchmark
# -------------------------------------------------------------------

def main() -> None:
    """Generate events and optionally send them to Amazon SQS."""

    args = parse_arguments()

    if args.volume <= 0:
        raise ValueError("Volume must be greater than zero.")

    # The run ID contains the volume and UTC time so every execution
    # can be identified separately.
    timestamp = datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )

    run_mode = "aws" if args.send else "local"
    run_id = f"{run_mode}-{args.volume}-{timestamp}"

    events = create_events(
        run_id=run_id,
        volume=args.volume,
    )

    first_message = events[0].model_dump_json()

    # A set removes duplicates, allowing us to confirm that all
    # generated event IDs are unique.
    event_ids = {
        str(event.payload.event_id)
        for event in events
    }

    print("LOCAL DRY-RUN: PASSED")
    print("Run ID:", run_id)
    print("Zone ID:", events[0].payload.zone_id)
    print("Events generated:", len(events))
    print("Unique event IDs:", len(event_ids))
    print(
        "First message size:",
        len(first_message.encode("utf-8")),
        "bytes",
    )

    print("\nFirst generated message:")
    print(first_message)

    if not args.send:
        print("\nNo AWS messages were sent.")
        return

    settings = BackendSettings()

    sqs_client = boto3.client(
        "sqs",
        region_name=settings.aws_region,
    )

    send_started = time.perf_counter()

    sent_total = send_events_to_sqs(
        sqs_client=sqs_client,
        queue_url=settings.sqs_queue_url,
        events=events,
    )

    send_duration = time.perf_counter() - send_started

    print("\nAWS SEND: COMPLETED")
    print("AWS region:", settings.aws_region)
    print("Events accepted by SQS:", sent_total)
    print(
        "SQS send duration:",
        f"{send_duration:.3f}",
        "seconds",
    )


if __name__ == "__main__":
    main()
