# FloodGuard Edge

[![FloodGuard CI/CD](https://github.com/maryhelenab/floodguard-edge/actions/workflows/main.yml/badge.svg)](https://github.com/maryhelenab/floodguard-edge/actions/workflows/main.yml)
[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=maryhelenab_floodguard-edge&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=maryhelenab_floodguard-edge)

FloodGuard Edge is a fog-assisted urban flood and drainage early-warning system developed for the Fog and Edge Computing module at the National College of Ireland.

The system simulates drainage sensors, processes readings close to the data source at the fog layer, sends validated risk events to AWS, stores them in DynamoDB, exposes query endpoints through API Gateway, and displays the results in a responsive web dashboard.

## Architecture

```text
Sensor Simulator
        |
        v
Mosquitto MQTT Broker
        |
        v
Fog Processing Node
        |
        v
MQTT-to-SQS Cloud Bridge
        |
        v
Amazon SQS
        |
        v
Ingestion Lambda
        |
        v
Amazon DynamoDB
        |
        v
Query Lambda
        |
        v
API Gateway HTTP API
        |
        v
HTML, CSS, JavaScript and Chart.js Dashboard
```

## Why Edge, Fog and Cloud?

| Layer | Responsibility | Benefit |
|---|---|---|
| Edge | Simulated drainage sensors generate local telemetry | Represents distributed IoT devices |
| Fog | Validates readings, calculates risk, detects alerts and buffers data locally | Supports low-latency decisions and continued operation during cloud outages |
| Cloud | Receives, stores and exposes events through scalable managed services | Provides durable storage, remote access and elastic processing |

The fog layer reduces dependence on continuous cloud connectivity. The cloud layer is used for scalable ingestion, persistence, querying and monitoring.

## Main Features

### Sensor and edge layer

- Four Dublin monitoring zones
- Five sensor types:
  - rainfall
  - water level
  - flow rate
  - soil saturation
  - drain blockage
- MQTT communication with QoS 1
- Unique event IDs and per-device sequence numbers
- Normal and developing-flood scenarios
- Local queueing when communication is unavailable

### Fog layer

- Pydantic validation of incoming telemetry
- Duplicate-event detection
- Stale-reading rejection
- Out-of-order reading rejection
- Independent rolling windows for each zone
- Derived drainage metrics
- Configurable risk weights and thresholds
- Risk levels from `INITIALISING` to `CRITICAL`
- Alert cooldown to reduce repeated notifications
- Local SQLite persistence
- Status and alert publication through MQTT

### Cloud layer

- MQTT-to-SQS cloud bridge
- Validated cloud event envelopes
- Amazon SQS asynchronous ingestion
- Dead-letter queue with `maxReceiveCount = 3`
- Lambda partial batch failure reporting
- DynamoDB event persistence
- Query Lambda
- API Gateway HTTP API
- Responsive S3-hosted dashboard

## Data Flow

1. Sensors publish telemetry to MQTT topics.
2. The fog node validates and processes the readings.
3. The fog node calculates a risk score for each zone.
4. Status and alert events are published to fog MQTT topics.
5. The cloud bridge validates the fog events and sends them to Amazon SQS.
6. The ingestion Lambda stores valid events in DynamoDB.
7. The query Lambda reads the stored events.
8. API Gateway exposes the data to the dashboard.

## AWS Resources

| Resource | Name |
|---|---|
| Main SQS queue | `floodguard-events` |
| Dead-letter queue | `floodguard-events-dlq` |
| DynamoDB table | `FloodGuardEvents` |
| Ingestion Lambda | `floodguard-ingestion` |
| Query Lambda | `floodguard-query` |
| HTTP API | `floodguard-api` |
| Dashboard bucket | `floodguard-edge-dashboard-25186396` |
| AWS region | `us-east-1` |

## API

Base URL:

```text
https://igsjnvt205.execute-api.us-east-1.amazonaws.com
```

Available endpoints:

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Check API health |
| GET | `/zones` | List monitored zones |
| GET | `/zones/{zone_id}/latest` | Return the latest status for a zone |
| GET | `/zones/{zone_id}/history?limit=20` | Return recent zone history |
| GET | `/zones/{zone_id}/alerts?limit=20` | Return recent alerts |

Example zone IDs:

```text
dublin-zone-01
dublin-zone-02
dublin-zone-03
dublin-zone-04
```

Health check:

```text
https://igsjnvt205.execute-api.us-east-1.amazonaws.com/health
```

## Dashboard

Online dashboard:

```text
http://floodguard-edge-dashboard-25186396.s3-website-us-east-1.amazonaws.com
```

The dashboard displays:

- API health status
- Four Dublin monitoring zones
- Current risk level and risk score
- Latest sensor readings
- Risk reasons
- Recommended action
- Risk-score history
- Rainfall history
- Water-level history
- Recent alerts
- Last-update time
- Manual and automatic refresh

The frontend contains no AWS credentials. It communicates only with the public API.

### Run the dashboard locally

From the repository root:

```powershell
.\.venv\Scripts\Activate.ps1
python -m http.server 8080 --directory dashboard
```

Open:

```text
http://localhost:8080
```

## CI/CD and Code Quality

The project uses GitHub Actions through:

```text
.github/workflows/main.yml
```

### Continuous Integration

Pull requests and pushes to `main` run:

- dependency installation
- automated tests
- coverage generation
- SonarQube Cloud analysis
- Sonar Quality Gate verification

### Continuous Deployment

After a successful push or merge to `main`, the deployment job:

- packages the ingestion Lambda
- updates `floodguard-ingestion`
- packages the query Lambda
- updates `floodguard-query`
- synchronises the dashboard with Amazon S3
- checks the public `/health` endpoint

Manual deployment remains available through `workflow_dispatch`.

AWS Academy credentials are stored as GitHub Actions secrets and must be refreshed when the temporary session expires.

### Latest verified quality results

| Measure | Result |
|---|---|
| Automated tests | 164 passed |
| Local test coverage | Approximately 92% |
| SonarQube Cloud coverage | 91.5% |
| Security rating | A |
| Reliability rating | A |
| Maintainability rating | A |
| Duplicated code | 0% |
| Quality Gate | Passed |

## Scalability Benchmark

The backend benchmark measures:

```text
Amazon SQS -> ingestion Lambda -> DynamoDB
```

It does not measure the complete Sensor -> MQTT -> Fog path.

The benchmark script is:

```text
scripts/scalability_test.py
```

### Safe local validation

This validates the generated events but does not contact AWS:

```powershell
python scripts\scalability_test.py
```

### Run the AWS benchmark

```powershell
python scripts\scalability_test.py `
  --send `
  --volumes 100 500 1000 `
  --repeat 1 `
  --timeout 420 `
  --interval 2
```

The script:

- creates valid FloodGuard status events
- uses unique IDs
- sends SQS batches of ten
- waits for DynamoDB persistence
- checks the main queue
- checks the DLQ increase
- calculates send and effective throughput
- saves CSV, JSON and Markdown evidence
- never deletes existing messages or database records

### Verified benchmark results

| Events | Sent | Stored | Failures | Send time | Total time | Effective throughput | Queue remaining | DLQ increase | Success |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | 100 | 100 | 0 | 1.584 s | 3.793 s | 26.365 events/s | 0 | 0 | 100% |
| 500 | 500 | 500 | 0 | 5.617 s | 5.726 s | 87.325 events/s | 0 | 0 | 100% |
| 1,000 | 1,000 | 1,000 | 0 | 12.633 s | 15.157 s | 65.975 events/s | 0 | 0 | 100% |

Across the three controlled runs, the backend persisted all 1,600 events with no failures, no remaining SQS messages and no DLQ increase.

Detailed evidence is stored in:

```text
docs/scalability_test_results.md
results/scalability_results.csv
results/scalability_results.json
```

### Benchmark limitations

- The benchmark covers the AWS backend only.
- SQS queue counts are approximate AWS metrics.
- Per-event P50, P95 and P99 latency are not reported because the current DynamoDB model does not store a precise ingestion-complete timestamp.
- AWS Academy session duration and Lambda concurrency can affect repeated results.
- Each volume was executed once in the final comparison.

## Testing

Run the complete test suite:

```powershell
python -m pytest -q
```

Latest verified result:

```text
164 passed
```

The test suite covers:

- event models
- configuration validation
- sensor generation
- MQTT topic parsing
- fog processing
- duplicate handling
- stale and out-of-order events
- rolling windows
- risk calculation
- alert generation
- cloud bridge behaviour
- Lambda ingestion
- DynamoDB persistence
- query routes
- dashboard-related backend responses

## Project Structure

```text
floodguard-edge/
|-- .github/                 # GitHub Actions CI/CD workflow
|-- backend/                 # Cloud models, bridge and AWS Lambda functions
|-- dashboard/               # HTML, CSS and JavaScript dashboard
|-- data/                    # Local fog persistence files
|-- device_simulator/        # Simulated drainage sensors
|-- docs/                    # Benchmark and project documentation
|-- fog_app/                 # Fog processing, MQTT logic and risk assessment
|-- infrastructure/          # AWS deployment packages and infrastructure files
|-- results/                 # CSV and JSON benchmark results
|-- scripts/                 # Scalability and utility scripts
|-- shared/                  # Shared models and utilities
|-- tests/                   # Automated unit and integration tests
|-- .env.example             # Environment variable example
|-- requirements.txt         # Python dependencies
`-- README.md
```

## Local Setup

### Requirements

- Python 3
- PowerShell
- Mosquitto MQTT broker
- AWS credentials for cloud operations
- Internet access for AWS, the API and Chart.js

### Create and activate the virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### Install dependencies

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Environment variables

Create the local environment file:

```powershell
Copy-Item .env.example .env
```

Update only the values required by the component being executed.

Never commit:

- AWS access keys
- AWS secret keys
- AWS session tokens
- passwords
- private endpoints
- `.env`

## Risk Levels

The fog layer produces:

```text
INITIALISING
NORMAL
WATCH
WARNING
HIGH
CRITICAL
```

The final risk level is based on:

- current sensor values
- recent trends
- drainage conditions
- derived metrics
- configured weights and thresholds
- safety overrides

## Sensor Units

| Sensor | Unit |
|---|---|
| Rainfall | mm/h |
| Water level | cm |
| Flow rate | L/s |
| Soil saturation | % |
| Drain blockage | % |

## Reliability

The solution includes:

- low-latency fog-side decisions
- local buffering during temporary connection failure
- SQLite fog persistence
- MQTT QoS 1
- event IDs and sequence numbers
- duplicate detection
- stale-reading validation
- out-of-order rejection
- asynchronous SQS ingestion
- SQS redrive policy
- dead-letter queue
- partial batch failure reporting
- validation before persistence
- DynamoDB durable storage
- independent dashboard requests using `Promise.allSettled()`
- automated deployment health verification

## Security

- AWS credentials are excluded from source control
- AWS credentials are not exposed in the dashboard
- GitHub Actions secrets store deployment credentials
- events are validated before cloud persistence
- frontend values are rendered with safe DOM text operations
- GitHub Actions are pinned to full commit SHAs
- SonarQube Cloud checks code quality and security
- IAM permissions should follow least privilege
- benchmark execution is safe by default and requires `--send`

## Demonstration Checklist

A complete project demonstration can show:

1. Sensor telemetry published through MQTT
2. Fog processing and risk calculation
3. A `developing_flood` scenario
4. HIGH or CRITICAL status and alert generation
5. Cloud bridge forwarding fog events to SQS
6. DynamoDB stored records
7. API `/health`, `/zones`, `/latest`, `/history` and `/alerts`
8. Online dashboard
9. SQS and DLQ configuration
10. GitHub Actions CI/CD
11. SonarQube Cloud Quality Gate
12. Scalability results for 100, 500 and 1,000 events

## Limitations

- Sensors are simulated rather than physical devices.
- The MQTT broker and fog node run locally.
- AWS Academy credentials are temporary.
- The dashboard uses a public API for the academic demonstration.
- The scalability benchmark measures the AWS backend rather than the full end-to-end path.
- The final benchmark comparison contains one run per volume.

## Future Work

Possible extensions include:

- physical drainage sensors
- AWS IoT Core integration
- CloudWatch alarms for Lambda errors and DLQ messages
- authenticated API access
- infrastructure as code
- repeated benchmark runs with statistical analysis
- per-event latency timestamps
- additional cities and zones
- predictive flood models

## Academic Context

This project demonstrates the practical use of edge, fog and cloud computing in an urban flood-monitoring scenario.

The edge layer represents distributed sensing devices. The fog layer provides low-latency validation, aggregation, risk assessment and resilience during temporary cloud outages. AWS managed services provide scalable ingestion, durable storage, remote queries and web-based monitoring.

The implementation also demonstrates software-engineering practices through automated tests, code coverage, static analysis, CI/CD, reproducible benchmark results and documented limitations.

## Repository

```text
https://github.com/maryhelenab/floodguard-edge
```

## Author

Maryhelen Albuquerque Bastos
Student ID: 25186396
MSc in Cloud Computing
National College of Ireland
