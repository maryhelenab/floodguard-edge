# FloodGuard Backend Scalability Test Results

## Methodology

Valid FloodGuard status events were sent to SQS in batches of ten. Each run used a unique `benchmark-*` zone. DynamoDB was checked until all expected records appeared or the timeout expired.

Measured path: **SQS → ingestion Lambda → DynamoDB**.

## Results

| Events | Run | Sent | Stored | Failures | Send time (s) | Total time (s) | Throughput (events/s) | Queue remaining | DLQ increase | Success |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | 1 | 100 | 100 | 0 | 1.584 | 3.793 | 26.365 | 0 | 0 | 100.000% |
| 500 | 1 | 500 | 500 | 0 | 5.617 | 5.726 | 87.325 | 0 | 0 | 100.000% |
| 1000 | 1 | 1000 | 1000 | 0 | 12.633 | 15.157 | 65.975 | 0 | 0 | 100.000% |

## Limitations

- The test measures the AWS backend from SQS, not the complete Sensor → MQTT → Fog path.
- SQS and DLQ message counts are approximate AWS metrics.
- P50, P95 and P99 per-event latency are not reported because DynamoDB does not store a precise ingestion-complete timestamp.
- AWS Academy credentials and Lambda concurrency can affect repeated results.
