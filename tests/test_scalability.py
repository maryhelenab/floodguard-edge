"""Essential tests for the FloodGuard scalability benchmark.

All AWS calls are mocked. These tests never send messages or change
real AWS resources.
"""

from argparse import Namespace
from unittest.mock import MagicMock

import pytest

from scripts import scalability_test as benchmark


def make_args(**changes) -> Namespace:
    """Create simple arguments used by main()."""

    values = {
        "send": False,
        "volumes": [100, 500, 1000],
        "repeat": 1,
        "region": "us-east-1",
        "queue_name": "floodguard-events",
        "queue_url": None,
        "dlq_url": None,
        "table_name": "FloodGuardEvents",
        "timeout": 180.0,
        "interval": 2.0,
    }
    values.update(changes)
    return Namespace(**values)


def make_result(**changes) -> dict:
    """Create one successful benchmark result."""

    values = {
        "run_id": "aws-100-r1-test",
        "zone_id": "benchmark-aws-100-r1-test",
        "volume": 100,
        "repetition": 1,
        "sent": 100,
        "stored": 100,
        "failures": 0,
        "success_percent": 100.0,
        "send_seconds": 1.0,
        "total_seconds": 2.0,
        "send_throughput": 100.0,
        "effective_throughput": 50.0,
        "queue_remaining": 0,
        "dlq_increase": 0,
        "timed_out": False,
        "started_at_utc": "2026-07-24T16:00:00.000Z",
        "finished_at_utc": "2026-07-24T16:00:02.000Z",
    }
    values.update(changes)
    return values


def test_create_events_returns_requested_unique_events() -> None:
    """The script must create the requested number of unique events."""

    events = benchmark.create_events("test-run", 20)
    event_ids = {str(event.payload.event_id) for event in events}

    assert len(events) == 20
    assert len(event_ids) == 20
    assert all(
        event.payload.zone_id == "benchmark-test-run"
        for event in events
    )


def test_send_events_uses_sqs_batches_of_ten() -> None:
    """SQS accepts a maximum of ten messages in each batch."""

    sqs = MagicMock()
    events = benchmark.create_events("batch-run", 23)

    sqs.send_message_batch.side_effect = lambda **kwargs: {
        "Successful": [
            {"Id": entry["Id"]}
            for entry in kwargs["Entries"]
        ],
        "Failed": [],
    }

    accepted = benchmark.send_events(sqs, "queue-url", events)

    batch_sizes = [
        len(call.kwargs["Entries"])
        for call in sqs.send_message_batch.call_args_list
    ]

    assert accepted == 23
    assert batch_sizes == [10, 10, 3]


def test_send_events_reports_sqs_failure() -> None:
    """The benchmark must stop if SQS rejects a message."""

    sqs = MagicMock()
    events = benchmark.create_events("failed-run", 1)
    sqs.send_message_batch.return_value = {
        "Successful": [],
        "Failed": [{"Id": "event-1", "Message": "Rejected"}],
    }

    with pytest.raises(RuntimeError, match="SQS rejected messages"):
        benchmark.send_events(sqs, "queue-url", events)


def test_count_records_supports_dynamodb_pagination() -> None:
    """The DynamoDB count must include every returned page."""

    table = MagicMock()
    table.query.side_effect = [
        {"Count": 700, "LastEvaluatedKey": {"pk": "next-page"}},
        {"Count": 300},
    ]

    total = benchmark.count_records(table, "benchmark-zone")

    assert total == 1000
    assert table.query.call_count == 2


def test_wait_for_records_finishes_when_data_is_stored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Polling finishes when DynamoDB reaches the expected count."""

    counts = iter([25, 100])
    monkeypatch.setattr(
        benchmark,
        "count_records",
        lambda *_: next(counts),
    )
    monkeypatch.setattr(benchmark.time, "sleep", lambda *_: None)

    stored, timed_out = benchmark.wait_for_records(
        MagicMock(),
        "benchmark-zone",
        expected=100,
        timeout=10,
        interval=0.01,
    )

    assert stored == 100
    assert timed_out is False


def test_run_test_calculates_main_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A completed run must report success, time and throughput."""

    monkeypatch.setattr(
        benchmark,
        "create_events",
        lambda *_: [MagicMock()] * 100,
    )
    monkeypatch.setattr(benchmark, "count_records", lambda *_: 0)
    monkeypatch.setattr(benchmark, "send_events", lambda *_: 100)
    monkeypatch.setattr(
        benchmark,
        "wait_for_records",
        lambda *_: (100, False),
    )

    queue_values = iter([0, 0, 0])
    monkeypatch.setattr(
        benchmark,
        "queue_count",
        lambda *_: next(queue_values),
    )

    times = iter([10.0, 11.0, 13.0, 16.0])
    monkeypatch.setattr(
        benchmark.time,
        "perf_counter",
        lambda: next(times),
    )

    result = benchmark.run_test(
        MagicMock(),
        MagicMock(),
        "queue-url",
        "dlq-url",
        volume=100,
        repetition=1,
        timeout=10,
        interval=1,
    )

    assert result["stored"] == 100
    assert result["failures"] == 0
    assert result["success_percent"] == 100.0
    assert result["send_seconds"] == 2.0
    assert result["total_seconds"] == 6.0
    assert result["effective_throughput"] == pytest.approx(16.667)
    assert result["dlq_increase"] == 0


def test_save_results_creates_evidence_files(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CSV, JSON and Markdown evidence must be created."""

    monkeypatch.setattr(benchmark, "PROJECT_ROOT", tmp_path)

    benchmark.save_results(
        [make_result()],
        make_args(volumes=[100]),
    )

    assert (
        tmp_path / "results" / "scalability_results.csv"
    ).exists()
    assert (
        tmp_path / "results" / "scalability_results.json"
    ).exists()
    assert (
        tmp_path / "docs" / "scalability_test_results.md"
    ).exists()


def test_main_dry_run_does_not_contact_aws(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Dry-run validates events without opening an AWS session."""

    monkeypatch.setattr(
        benchmark,
        "parse_args",
        lambda: make_args(send=False, volumes=[2]),
    )

    aws_session = MagicMock()
    monkeypatch.setattr(benchmark.boto3, "Session", aws_session)

    benchmark.main()

    aws_session.assert_not_called()
    assert "LOCAL VALIDATION COMPLETED SUCCESSFULLY" in (
        capsys.readouterr().out
    )


@pytest.mark.parametrize(
    "args",
    [
        make_args(volumes=[0]),
        make_args(repeat=0),
        make_args(timeout=0),
        make_args(interval=0),
    ],
)
def test_main_rejects_invalid_arguments(
    args: Namespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid volumes and timing values must be rejected."""

    monkeypatch.setattr(benchmark, "parse_args", lambda: args)

    with pytest.raises(SystemExit):
        benchmark.main()
