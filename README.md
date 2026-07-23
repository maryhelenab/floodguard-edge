# FloodGuard Edge

FloodGuard Edge is a fog-assisted urban flood and drainage early-warning system.

The project simulates environmental and drainage sensors distributed across multiple urban zones. Sensor telemetry is validated locally and published through MQTT using Quality of Service level 1.

A local fog node consumes the telemetry, maintains independent state for each urban zone, calculates flood risk, publishes status and alert events, and persists processed results locally in SQLite.

A serverless AWS backend receives fog events through Amazon SQS, processes them with AWS Lambda, stores them in Amazon DynamoDB, and exposes status, history, and alert information through an Amazon API Gateway HTTP API.

## Repository

GitHub:

```text
https://github.com/maryhelenab/floodguard-edge
```

## System Architecture

```text
Sensor Simulator
        |
        v
Local Mosquitto MQTT Broker
        |
        v
Fog Processing Node
        |
        +----------------------+
        |                      |
        v                      v
Local SQLite            MQTT Fog Events
                               |
                               v
                    MQTT-to-SQS Cloud Bridge
                               |
                               v
                         Amazon SQS
                               |
                               v
                    AWS Lambda Ingestion
                               |
                               v
                      Amazon DynamoDB
                               |
                               v
                      AWS Lambda Query
                               |
                               v
                Amazon API Gateway HTTP API
```

The system follows a hybrid edge, fog, and cloud architecture:

- Sensor generation and validation occur at the edge.
- Flood-risk analysis occurs at the fog layer.
- Event buffering, scalable processing, persistence, and public queries occur in AWS.

## Current Implemented Features

### Edge Sensor Layer

- Four simulated urban zones
- Five environmental and drainage sensor types
- Twenty simulated sensor devices
- Pydantic telemetry validation
- Unique UUID event identifiers
- Independent sequence numbers for every device
- MQTT telemetry publication using QoS 1
- One local queue for each sensor device
- Separate telemetry generation and MQTT dispatch intervals
- Normal and developing-flood simulation scenarios
- Correlated flood behaviour across sensor types
- Deterministic simulation using a fixed random seed
- Structured application logging
- MQTT connection error handling
- Manual process termination using `Ctrl+C`

### Fog Processing Layer

- MQTT wildcard subscription for raw telemetry
- MQTT topic parsing and validation
- Topic and payload consistency validation
- Malformed JSON rejection
- Pydantic payload validation
- Bounded event deduplication
- Stale telemetry rejection
- Out-of-order sequence rejection
- Independent rolling sensor windows for each urban zone
- Warm-up state until all required sensors are available
- Deterministic flood-risk calculation
- Explainable risk reasons and derived metrics
- Configurable status publication interval
- Configurable alert cooldown
- MQTT publication of fog status events
- MQTT publication of flood-risk alerts
- Local SQLite persistence
- Automated unit and integration testing
- End-to-end validation using a real Mosquitto broker

### Serverless Cloud Backend Layer

- MQTT-to-SQS cloud bridge
- Pydantic validation of fog events before cloud delivery
- Amazon SQS event buffering
- Amazon SQS dead-letter queue
- Lambda-based event ingestion
- Partial SQS batch failure reporting
- DynamoDB status and alert persistence
- Lambda-based query service
- Amazon API Gateway HTTP API
- Public zone, status, history, and alert endpoints
- Reproducible Lambda deployment ZIP packages
- End-to-end serverless cloud validation
- 121 automated tests passing

## Simulated Zones

The simulator currently includes:

- `dublin-zone-01`
- `dublin-zone-02`
- `dublin-zone-03`
- `dublin-zone-04`

## Sensor Types

| Sensor | Unit | Purpose |
|---|---|---|
| Rainfall | mm/h | Measures rainfall intensity |
| Water level | cm | Measures water accumulation |
| Flow rate | L/s | Measures drainage water flow |
| Soil saturation | % | Measures soil saturation |
| Drain blockage | % | Estimates drainage obstruction |

## Project Structure

```text
floodguard-edge/
|-- backend/
|   |-- cloud_bridge.py
|   |-- cloud_models.py
|   |-- config.py
|   |-- lambda_ingestion.py
|   `-- lambda_query.py
|-- dashboard/
|-- data/
|   `-- fog/
|       `-- fog_events.db
|-- device_simulator/
|   |-- config.json
|   `-- sensor.py
|-- docs/
|-- fog_app/
|   |-- config/
|   |   |-- fog_config.json
|   |   `-- settings.py
|   |-- mqtt/
|   |   |-- fog_node.py
|   |   `-- topic_parser.py
|   |-- processing/
|   |   |-- deduplication.py
|   |   |-- message_validation.py
|   |   |-- processor.py
|   |   |-- publication_policy.py
|   |   |-- risk_engine.py
|   |   `-- zone_state.py
|   |-- models.py
|   `-- persistence.py
|-- infrastructure/
|   `-- package_lambdas.py
|-- shared/
|   `-- telemetry.py
|-- tests/
|   `-- test_cloud_models.py
|-- .env.example
|-- .gitignore
|-- docker-compose.yml
|-- requirements.txt
`-- README.md
```

The `dashboard` and `docs` directories are retained for the presentation interface, diagrams, report evidence, and future documentation.

## Requirements

The implementation requires:

- Python 3.13 or compatible
- Mosquitto MQTT Broker
- An AWS Academy Learner Lab or AWS account
- Temporary AWS credentials with access to:
  - Amazon SQS
  - AWS Lambda
  - Amazon DynamoDB
  - Amazon API Gateway
  - Amazon CloudWatch
- Python packages listed in `requirements.txt`

## Environment Setup

Clone the repository:

```powershell
git clone https://github.com/maryhelenab/floodguard-edge.git
cd floodguard-edge
```

Create a Python virtual environment:

```powershell
python -m venv .venv
```

Activate the virtual environment in PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install the project dependencies:

```powershell
pip install -r requirements.txt
```

Confirm the Python version:

```powershell
python --version
```

## Environment Configuration

Copy the environment template:

```powershell
Copy-Item .env.example .env
```

The local `.env` file must contain the real Amazon SQS queue URL:

```env
BACKEND_AWS_REGION=us-east-1
BACKEND_SQS_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/ACCOUNT_ID/floodguard-events

BACKEND_MQTT_HOST=localhost
BACKEND_MQTT_PORT=1883
BACKEND_MQTT_QOS=1
BACKEND_MQTT_STATUS_TOPIC=city/drainage/+/fog/status
BACKEND_MQTT_ALERT_TOPIC=city/drainage/+/fog/alert
BACKEND_CLOUD_BRIDGE_CLIENT_ID=floodguard-cloud-bridge
```

Replace `ACCOUNT_ID` with the AWS account ID used during deployment.

The `.env` file is excluded from Git and must never be committed.

AWS credentials must be stored in the local AWS shared credentials file:

```text
C:\Users\<username>\.aws\credentials
```

Temporary AWS Academy credentials may expire when the Learner Lab session ends. Refresh the local credentials before restarting the cloud bridge in a new lab session.

Do not place AWS access keys, secret keys, or session tokens in:

- Source-code files
- `.env.example`
- `README.md`
- Git commits
- GitHub Issues
- Screenshots submitted publicly

## MQTT Broker

The local implementation connects to Mosquitto using:

```text
Host: localhost
Port: 1883
QoS: 1
```

Check whether the Mosquitto Windows service is running:

```powershell
Get-Service mosquitto
```

Start the Mosquitto service when necessary:

```powershell
Start-Service mosquitto
```

Confirm that the broker is reachable:

```powershell
Test-NetConnection -ComputerName localhost -Port 1883
```

A successful connection displays:

```text
TcpTestSucceeded : True
```

## Running the Application

The complete system requires three local processes:

1. Fog processing node
2. MQTT-to-SQS cloud bridge
3. Sensor simulator

Amazon SQS automatically invokes the ingestion Lambda. No additional local SQS consumer is required.

### Terminal 1 — Fog Node

From the repository root:

```powershell
python -m fog_app.mqtt.fog_node
```

The fog node subscribes to:

```text
city/drainage/+/+/telemetry
```

It publishes processed status and alert events to MQTT.

### Terminal 2 — Cloud Bridge

From the repository root:

```powershell
python -m backend.cloud_bridge
```

The cloud bridge subscribes to:

```text
city/drainage/+/fog/status
city/drainage/+/fog/alert
```

It validates each fog event and sends valid events to Amazon SQS.

### Terminal 3 — Sensor Simulator

From the repository root:

```powershell
python -m device_simulator.sensor
```

The simulator:

1. Loads `device_simulator/config.json`.
2. Connects to the local MQTT broker.
3. Creates one local queue for every simulated sensor device.
4. Generates readings for every configured zone and sensor.
5. Assigns a unique UUID to every reading.
6. Validates every telemetry message using Pydantic.
7. Stores generated telemetry in the corresponding local queue.
8. Dispatches queued messages using MQTT QoS 1.
9. Records operations using structured logging.
10. Disconnects after completing the configured simulation.

## MQTT Topics

### Raw Sensor Telemetry

Telemetry uses:

```text
city/drainage/{zone_id}/{sensor_type}/telemetry
```

Example:

```text
city/drainage/dublin-zone-01/rainfall/telemetry
```

The fog node subscribes to:

```text
city/drainage/+/+/telemetry
```

### Fog Status

Fog status events use:

```text
city/drainage/{zone_id}/fog/status
```

Example:

```text
city/drainage/dublin-zone-01/fog/status
```

### Fog Alerts

Fog alert events use:

```text
city/drainage/{zone_id}/fog/alert
```

Example:

```text
city/drainage/dublin-zone-01/fog/alert
```

Subscribe to all FloodGuard messages:

```powershell
mosquitto_sub -h localhost -p 1883 -t "city/drainage/#" -q 1 -v
```

When Mosquitto is not available through the Windows `PATH`, use:

```powershell
& "C:\Program Files\mosquitto\mosquitto_sub.exe" `
    -h localhost `
    -p 1883 `
    -t "city/drainage/#" `
    -q 1 `
    -v
```

## Telemetry Message Format

Example telemetry payload:

```json
{
  "event_id": "8ea43af6-25c3-4e1e-a1cc-9759cb9711fe",
  "device_id": "dublin-zone-01-rainfall-01",
  "zone_id": "dublin-zone-01",
  "sensor_type": "rainfall",
  "value": 5.12,
  "unit": "mm/h",
  "sequence": 1,
  "timestamp": "2026-07-22T09:58:25.323000Z"
}
```

Every message is validated before publication.

Validation checks include:

- Non-empty device and zone identifiers
- Supported sensor type
- Non-negative sensor value
- Non-empty measurement unit
- Sequence number of at least one
- Valid timestamp
- Valid UUID event identifier

## Simulation Scenarios

The active scenario is selected in:

```text
device_simulator/config.json
```

### Normal Scenario

```json
"scenario": "normal"
```

The normal scenario generates readings using the standard configured sensor ranges.

### Developing Flood Scenario

```json
"scenario": "developing_flood"
```

The developing-flood scenario models correlated sensor behaviour:

- Rainfall intensity increases.
- Soil saturation increases.
- Drain blockage accelerates.
- Drain flow reaches a peak.
- Drain flow may decline as blockage reduces drainage capacity.
- Water level rises more rapidly toward the end of the scenario.
- Combined sensor behaviour increases the calculated flood-risk score.

A fixed random seed makes generated values reproducible during tests and demonstrations.

## Fog Processing Pipeline

Each raw telemetry message follows this pipeline:

```text
MQTT telemetry
      |
      v
Topic parsing
      |
      v
JSON decoding
      |
      v
Pydantic validation
      |
      v
Topic and payload consistency validation
      |
      v
Freshness validation
      |
      v
Event deduplication
      |
      v
Sequence validation
      |
      v
Independent zone-state update
      |
      v
Flood-risk calculation
      |
      v
Status and alert publication
      |
      v
Local SQLite persistence
```

A rejected message does not update the rolling sensor windows and does not produce a new status or alert event.

## Fog Message Validation

The fog processor rejects:

- Malformed JSON
- Invalid Pydantic payloads
- Invalid MQTT topic structures
- Topic and payload mismatches
- Unknown urban zones
- Duplicate event identifiers
- Stale telemetry
- Out-of-order sequence numbers

The processor maintains separate validation state and sensor state for every configured urban zone.

## Zone State and Rolling Windows

Each urban zone maintains a separate rolling window for:

- Rainfall
- Water level
- Flow rate
- Soil saturation
- Drain blockage

The configured rolling-window duration is 60 seconds.

The fog node initially produces an `INITIALISING` status while waiting for all five required sensor types.

After all required sensor data becomes available, the risk engine calculates the current flood-risk state.

## Flood-Risk Calculation

The deterministic risk engine evaluates:

- Rainfall intensity
- Current water level
- Water-level trend
- Drain flow utilisation
- Soil saturation
- Drain blockage
- Combined drainage stress

The resulting fog status contains:

- Event identifier
- Fog-node identifier
- Zone identifier
- Risk level
- Numerical risk score
- Computation timestamp
- Current sensor snapshot
- Derived metrics
- Sensor sample counts
- Human-readable risk reasons
- Missing sensor types
- Source telemetry event identifiers

Fog alerts also contain:

- Alert identifier
- Alert severity
- Alert message
- Recommended local action
- Trigger timestamp
- Source status event identifier

## Fog Status and Alert Policies

Fog status events are published:

- At the configured status interval
- When the zone risk level changes
- When the initial warm-up state is completed

Fog alerts are controlled through:

- Configured alert risk levels
- Risk-level escalation
- Alert cooldown
- Independent publication state for every zone

These policies reduce unnecessary duplicate messages while preserving important local warnings.

## Local Persistence

Processed fog outputs are stored locally in:

```text
data/fog/fog_events.db
```

The SQLite database contains:

| Table | Purpose |
|---|---|
| `processed_statuses` | Stores generated fog status events |
| `alerts` | Stores generated flood alerts |

The fog node can continue local validation, risk calculation, alerting, and persistence without requiring an active cloud connection.

## Serverless Cloud Backend

### Cloud Event Flow

```text
Fog Status or Alert
        |
        v
Local MQTT Broker
        |
        v
Cloud Bridge
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
```

### Cloud Models

`backend/cloud_models.py` defines the validated event envelope used by the cloud bridge.

The model:

- Parses fog MQTT topics
- Identifies status and alert event types
- Validates JSON payloads
- Checks topic and payload zone consistency
- Extracts event identifiers and timestamps
- Produces a consistent message body for Amazon SQS

### Cloud Bridge

`backend/cloud_bridge.py`:

- Loads configuration from `.env`
- Connects to the local Mosquitto broker
- Subscribes to fog status and alert topics
- Validates received messages
- Sends valid events to the configured SQS queue
- Logs the SQS message identifier, event type, and zone
- Rejects invalid messages before cloud delivery

### AWS Resources

The deployed backend uses:

```text
AWS Region: us-east-1

SQS main queue:
floodguard-events

SQS dead-letter queue:
floodguard-events-dlq

DynamoDB table:
FloodGuardEvents

Ingestion Lambda:
floodguard-ingestion

Query Lambda:
floodguard-query

API Gateway HTTP API:
floodguard-api
```

The SQS main queue is connected to the dead-letter queue with a maximum receive count of three.

Messages that repeatedly fail processing can therefore be isolated for investigation instead of being retried indefinitely.

## Lambda Ingestion

The ingestion function source is:

```text
backend/lambda_ingestion.py
```

Lambda configuration:

```text
Function name: floodguard-ingestion
Handler: lambda_ingestion.lambda_handler
Runtime: Python
Architecture: x86_64
Memory: 128 MB
Timeout: 5 seconds
```

Required Lambda environment variable:

```text
DYNAMODB_TABLE_NAME=FloodGuardEvents
```

The SQS trigger uses:

```text
Queue: floodguard-events
Batch size: 10
Partial batch failure reporting: enabled
```

The ingestion Lambda:

1. Receives SQS records.
2. Decodes each event envelope.
3. Identifies status or alert events.
4. Generates DynamoDB partition and sort keys.
5. Stores the complete event payload.
6. Returns failed message identifiers using `batchItemFailures`.
7. Allows successfully processed records to be removed from the queue.

## DynamoDB Data Model

The table uses:

```text
Table name: FloodGuardEvents
Partition key: pk
Sort key: sk
```

Partition-key format:

```text
ZONE#{zone_id}
```

Example:

```text
ZONE#dublin-zone-01
```

Status sort-key format:

```text
STATUS#{timestamp_ms}#{event_id}
```

Alert sort-key format:

```text
ALERT#{timestamp_ms}#{event_id}
```

Examples:

```text
STATUS#1784840500262#ae78bcfb-98e5-4b3d-bb1d-14064f7a03c7
ALERT#1784840500417#7bf1aef6-a443-4920-847d-23a3b6747f0f
```

This model supports:

- Independent data access by zone
- Chronological event ordering
- Efficient latest-status queries
- Status-history queries
- Alert-history queries
- Unique records using event identifiers

## Lambda Query Service

The query function source is:

```text
backend/lambda_query.py
```

Lambda configuration:

```text
Function name: floodguard-query
Handler: lambda_query.lambda_handler
Runtime: Python
Architecture: x86_64
Memory: 128 MB
Timeout: 5 seconds
```

Required Lambda environment variable:

```text
DYNAMODB_TABLE_NAME=FloodGuardEvents
```

The query Lambda:

- Validates the requested zone
- Reads status and alert records from DynamoDB
- Returns the most recent status
- Supports configurable query limits
- Converts DynamoDB numeric values into JSON-compatible values
- Returns API Gateway-compatible HTTP responses
- Includes CORS response headers

## Public API Routes

The API Gateway HTTP API exposes:

```text
GET /health
GET /zones
GET /zones/{zone_id}/latest
GET /zones/{zone_id}/history
GET /zones/{zone_id}/alerts
```

Optional query parameter:

```text
limit
```

Examples:

```text
GET /zones/dublin-zone-01/history?limit=5
GET /zones/dublin-zone-01/alerts?limit=10
```

The supported limit range is:

```text
1 to 100
```

The public API base URL has the following format:

```text
https://<api-id>.execute-api.us-east-1.amazonaws.com
```

The API identifier may change when AWS Learner Lab resources are recreated.

### Testing the Public API

Set the API URL in PowerShell:

```powershell
$BaseUrl = "https://<api-id>.execute-api.us-east-1.amazonaws.com"
```

Health check:

```powershell
Invoke-RestMethod `
    -Uri "$BaseUrl/health" `
    -Method Get
```

List zones:

```powershell
Invoke-RestMethod `
    -Uri "$BaseUrl/zones" `
    -Method Get |
    ConvertTo-Json -Depth 5
```

Latest zone status:

```powershell
Invoke-RestMethod `
    -Uri "$BaseUrl/zones/dublin-zone-01/latest" `
    -Method Get |
    ConvertTo-Json -Depth 10
```

Status history:

```powershell
Invoke-RestMethod `
    -Uri "$BaseUrl/zones/dublin-zone-01/history?limit=5" `
    -Method Get |
    ConvertTo-Json -Depth 10
```

Alert history:

```powershell
Invoke-RestMethod `
    -Uri "$BaseUrl/zones/dublin-zone-01/alerts?limit=5" `
    -Method Get |
    ConvertTo-Json -Depth 10
```

Example health response:

```json
{
  "status": "healthy",
  "service": "FloodGuard Query Lambda",
  "table": "FloodGuardEvents"
}
```

## Lambda Packaging

Create both Lambda deployment packages with:

```powershell
python infrastructure/package_lambdas.py
```

The script creates:

```text
infrastructure/floodguard-ingestion-lambda.zip
infrastructure/floodguard-query-lambda.zip
```

The ingestion ZIP contains:

```text
lambda_ingestion.py
```

The query ZIP contains:

```text
lambda_query.py
```

The generated ZIP files are excluded from Git because they can be recreated from the Lambda source files.

The `.gitignore` rules include:

```gitignore
# AWS Lambda deployment packages
infrastructure/*.zip
infrastructure/lambda_*_package/
```

## End-to-End Validation

### Local Fog Validation

The local fog-processing implementation was validated using a real Mosquitto broker.

The test confirmed:

- MQTT telemetry ingestion using QoS 1
- Wildcard subscription by the fog node
- Warm-up status publication
- Multi-sensor correlation within one zone
- Flood-risk detection
- Explainable risk reasons
- Status publication
- Alert publication
- Source-event traceability
- SQLite persistence

### Serverless Cloud Validation

The final serverless flow was successfully validated:

```text
Sensor Simulator
        |
        v
Mosquitto MQTT
        |
        v
Fog Node
        |
        v
Cloud Bridge
        |
        v
Amazon SQS
        |
        v
Ingestion Lambda
        |
        v
DynamoDB
        |
        v
Query Lambda
        |
        v
API Gateway
```

During the final `developing_flood` validation:

```text
Status records before: 3
Status records after: 5

Alert records before: 2
Alert records after: 3

Latest risk level: HIGH
Latest risk score: 57.25
```

The latest event was returned through the public API after being:

1. Generated by the local sensor simulator.
2. Processed by the fog node.
3. Published through MQTT.
4. forwarded to Amazon SQS by the cloud bridge.
5. Processed automatically by the ingestion Lambda.
6. Stored in DynamoDB.
7. Queried by the query Lambda.
8. Returned through API Gateway.

This confirms the complete edge-to-fog-to-cloud processing pipeline.

## Logging

The simulator, fog node, and cloud bridge use structured logging.

Log format:

```text
timestamp | log level | module | message
```

Example cloud-bridge output:

```text
2026-07-23 23:07:45,416 | INFO | __main__ | Event sent to SQS: message_id=<message-id>, type=alert, zone=dublin-zone-04
```

Normal operations use the `INFO` level.

Rejected messages and unexpected MQTT disconnections use the `WARNING` level.

Publication, validation, persistence, and cloud-delivery failures use the `ERROR` level.

AWS Lambda execution logs are available in Amazon CloudWatch.

## Running the Tests

Run the complete automated test suite:

```powershell
pytest -q
```

Latest confirmed result:

```text
121 passed
```

The automated tests cover:

- Shared telemetry-model validation
- Sensor simulation
- Normal and developing-flood scenarios
- Local sensor queues
- MQTT publication behaviour
- MQTT topic parsing
- Topic and payload consistency
- Event deduplication
- Message freshness
- Sequence ordering
- Independent zone state
- Rolling sensor windows
- Flood-risk calculation
- Status publication policy
- Alert cooldown policy
- Fog status and alert models
- SQLite persistence
- Central fog-message processing
- MQTT fog-node behaviour
- Cloud MQTT-topic parsing
- Cloud event-envelope validation
- Status and alert cloud models
- Topic and payload zone consistency

Run tests with code coverage:

```powershell
pytest -v `
    --cov=device_simulator `
    --cov=fog_app `
    --cov=shared `
    --cov=backend `
    --cov-report=term-missing
```

Check Python syntax:

```powershell
python -m compileall backend infrastructure tests -q
```

Check Git formatting errors:

```powershell
git diff --check
```

## Security and Git Hygiene

The following files and directories must remain excluded from Git:

```text
.env
.venv/
__pycache__/
.pytest_cache/
AWS Lambda ZIP packages
Local AWS credentials
SQLite temporary files when configured as ignored
```

Check whether `.env` is ignored:

```powershell
git check-ignore .env
```

Check for accidentally committed AWS access-key patterns:

```powershell
git grep -n -I -E "ASIA[0-9A-Z]{16}|AKIA[0-9A-Z]{16}" -- .
```

The access-key check should return no output.

## Current Development Status

### Day 1 — Edge Sensor Simulation

Completed:

- Multi-zone sensor simulation
- Five sensor types
- Twenty simulated devices
- Pydantic telemetry validation
- MQTT QoS 1 publication
- Per-device local queues
- Independent sequence tracking
- Reproducible simulation scenarios
- Correlated developing-flood behaviour
- Automated testing

### Day 2 — Fog Processing

Completed:

- MQTT telemetry subscription
- Topic and payload validation
- Event deduplication
- Freshness validation
- Sequence validation
- Independent zone state
- Rolling sensor windows
- Deterministic risk engine
- Status publication policy
- Alert cooldown policy
- MQTT fog adapter
- SQLite persistence
- Unit and integration testing
- Real Mosquitto end-to-end validation

Day 2 was completed before the serverless backend implementation began.

### Day 3 — Scalable Serverless Backend

Completed:

- Cloud event models
- MQTT-to-SQS bridge
- SQS main queue
- SQS dead-letter queue
- SQS redrive policy
- Lambda ingestion function
- Partial batch failure reporting
- DynamoDB event table
- Lambda query function
- API Gateway HTTP API
- Public health endpoint
- Public zone-list endpoint
- Public latest-status endpoint
- Public status-history endpoint
- Public alert-history endpoint
- Reproducible Lambda packaging
- End-to-end developing-flood cloud validation
- Security checks for AWS credentials
- 121 automated tests passing

## Final Implemented Flow

```text
Edge Sensors
    |
    v
MQTT Telemetry
    |
    v
Fog Validation and Risk Processing
    |
    +------------------------+
    |                        |
    v                        v
SQLite Persistence      Fog MQTT Events
                                |
                                v
                         Cloud Bridge
                                |
                                v
                           Amazon SQS
                                |
                                v
                      Ingestion Lambda
                                |
                                v
                          DynamoDB
                                |
                                v
                         Query Lambda
                                |
                                v
                     API Gateway HTTP API
```

FloodGuard Edge demonstrates how edge sensing, fog analytics, asynchronous cloud messaging, serverless processing, NoSQL persistence, and public cloud APIs can be combined into a scalable urban flood early-warning architecture.