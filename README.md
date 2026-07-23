# FloodGuard Edge

FloodGuard Edge is a fog-assisted urban flood and drainage early-warning system.

The project simulates environmental and drainage sensors distributed across multiple urban zones. Sensor telemetry is validated locally and published through MQTT using Quality of Service level 1.

A local fog node consumes the telemetry, validates message freshness and ordering, maintains independent state for each urban zone, calculates flood risk, publishes status and alert events, and persists processed results in SQLite.

## Repository

GitHub:

https://github.com/maryhelenab/floodguard-edge

## Current Implemented Features

### Edge Sensor Layer

- Four simulated urban zones
- Five environmental and drainage sensor types
- Pydantic telemetry validation
- Unique UUID event identifiers
- Independent sequence numbers for each sensor device
- MQTT telemetry publication using Quality of Service level 1
- One local queue for each simulated sensor device
- Separate telemetry generation and MQTT dispatch intervals
- Normal and developing-flood simulation scenarios
- Correlated flood behaviour across sensor types
- Deterministic simulation using a fixed random seed
- Structured logging
- MQTT connection error handling
- Graceful shutdown using `Ctrl+C`

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
- MQTT publication of critical alerts
- Local SQLite persistence
- Automated unit and integration testing
- End-to-end validation using a real Mosquitto broker
- 114 automated tests passing

## Simulated Zones

The simulator currently includes:

- `dublin-zone-01`
- `dublin-zone-02`
- `dublin-zone-03`
- `dublin-zone-04`

## Sensor Types

The following sensors are simulated:

| Sensor | Unit | Purpose |
|---|---|---|
| Rainfall | mm/h | Measures rainfall intensity |
| Water level | cm | Measures water accumulation |
| Flow rate | L/s | Measures drainage water flow |
| Soil saturation | % | Measures how saturated the soil is |
| Drain blockage | % | Estimates drainage obstruction |

## Project Structure

```text
floodguard-edge/
|-- backend/
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
|-- shared/
|   `-- telemetry.py
|-- tests/
|-- .env.example
|-- docker-compose.yml
`-- README.md
```

## Requirements

The current local implementation requires:

- Python 3.13 or compatible
- Mosquitto MQTT Broker
- Paho MQTT
- Pydantic
- Pytest
- Pytest Coverage

## Environment Setup

Create a virtual environment:

```powershell
python -m venv .venv
```

Activate it in PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install the required packages:

```powershell
pip install paho-mqtt pydantic pytest pytest-cov
```

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

## Running the Sensor Simulator

From the repository root, run:

```powershell
python -m device_simulator.sensor
```

The simulator will:

1. Load `device_simulator/config.json`.
2. Connect to the local MQTT broker.
3. Create one local queue for each simulated sensor device.
4. Generate readings for every configured zone and sensor.
5. Assign a unique UUID event identifier to each reading.
6. Validate each message using Pydantic.
7. Store generated telemetry in the corresponding local queue.
8. Dispatch queued messages separately using MQTT QoS 1.
9. Record operations using structured logging.
10. Disconnect safely after completion or when interrupted using `Ctrl+C`.

## MQTT Topics

### Raw Sensor Telemetry

Telemetry uses the following topic structure:

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

Fog status events are published to:

```text
city/drainage/{zone_id}/fog/status
```

Example:

```text
city/drainage/dublin-zone-01/fog/status
```

### Fog Alerts

Fog alerts are published to:

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

On Windows, when Mosquitto is not available through `PATH`, use:

```powershell
& "C:\Program Files\mosquitto\mosquitto_sub.exe" `
    -h localhost `
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

Each message is validated before publication.

The validation model checks that:

- Device and zone identifiers are not empty.
- The sensor type is supported.
- The sensor value is not negative.
- The measurement unit is not empty.
- The sequence number is at least one.
- The timestamp is valid.
- The event identifier is a valid UUID.

## Simulation Scenarios

The active scenario is selected in:

```text
device_simulator/config.json
```

### Normal Scenario

```json
"scenario": "normal"
```

The normal scenario generates readings using the configured sensor ranges.

### Developing Flood Scenario

```json
"scenario": "developing_flood"
```

The developing-flood scenario models correlated sensor behaviour:

- Rainfall intensity increases.
- Drain blockage accelerates.
- Flow rate reaches a peak and then declines as drainage capacity is reduced.
- Water level rises more rapidly near the end of the scenario.
- Soil saturation contributes to increased surface-runoff risk.

A fixed random seed makes generated values reproducible during testing.

## Running the Fog Node

Start the Mosquitto broker before running the fog application.

From the repository root, run:

```powershell
python -m fog_app.mqtt.fog_node
```

The fog node connects to `localhost:1883` and subscribes to:

```text
city/drainage/+/+/telemetry
```

Stop the fog node safely using `Ctrl+C`.

## Fog Processing Pipeline

Each MQTT telemetry message follows this processing pipeline:

```text
MQTT telemetry
      |
      v
Topic parsing
      |
      v
JSON and Pydantic validation
      |
      v
Topic and payload consistency validation
      |
      v
Freshness, deduplication, and sequence validation
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
SQLite persistence
```

A rejected message does not update the rolling sensor windows and does not produce a status or alert.

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

The processor maintains independent validation and sensor state for each configured zone.

## Zone State and Rolling Windows

Each urban zone maintains a separate rolling window for:

- Rainfall
- Water level
- Flow rate
- Soil saturation
- Drain blockage

The configured rolling-window duration is 60 seconds.

The fog node initially publishes an `INITIALISING` status while waiting for all five required sensor types.

Once all required sensor data is available, the risk engine calculates the current flood-risk state.

## Flood-Risk Calculation

The deterministic risk engine evaluates:

- Rainfall intensity
- Current water level
- Water-level trend
- Drain flow utilisation
- Soil saturation
- Drain blockage
- Combined drainage stress

The resulting fog status includes:

- Risk level
- Numerical risk score
- Current sensor snapshot
- Derived metrics
- Sample counts
- Human-readable reasons
- Missing sensor types
- Source telemetry event identifiers

Critical alerts also include:

- Alert severity
- Alert message
- Recommended local response
- Source status event identifier

## Fog Status and Alert Policies

Fog status events are published:

- At the configured status interval
- When the zone risk level changes
- When the initial warm-up state is completed

Fog alerts are controlled using:

- Configured alert risk levels
- Risk-level escalation
- Alert cooldown
- Independent publication state for each zone

These policies reduce unnecessary duplicate messages while preserving important local warnings.

## Local Persistence

Processed fog outputs are stored in:

```text
data/fog/fog_events.db
```

The SQLite database contains:

| Table | Purpose |
|---|---|
| `processed_statuses` | Stores generated fog status events |
| `alerts` | Stores generated flood alerts |

The fog node can continue local validation, risk calculation, alerting, and persistence without requiring a cloud connection.

## End-to-End Validation

The implementation was validated using a real Mosquitto broker and five telemetry messages for `dublin-zone-01`.

The test first produced:

```text
Risk level: INITIALISING
```

after receiving only the rainfall sensor.

After readings from all five sensors were received, the confirmed result was:

```text
Risk level: CRITICAL
Risk score: 62.33
Alert severity: CRITICAL
Recommended action: Activate the local emergency response immediately.
```

The test confirmed:

- MQTT telemetry ingestion using QoS 1
- Wildcard subscription by the fog node
- Warm-up status publication
- Multi-sensor correlation within one zone
- Critical-risk detection
- Explainable risk reasons
- Status publication
- Alert publication
- Source-event traceability
- SQLite persistence

The resulting local SQLite database contained:

```text
processed_statuses: 3
alerts: 1
```

## Logging

The simulator and fog node use structured logging with the following format:

```text
timestamp | log level | module | message
```

Example fog-node startup:

```text
2026-07-23 02:14:37,336 | INFO | __main__ | Starting fog node fog-node-dublin-01 using broker localhost:1883.
2026-07-23 02:14:37,362 | INFO | __main__ | Fog node connected and subscribed to city/drainage/+/+/telemetry with QoS 1.
```

Normal operations use the `INFO` level. Rejected messages and unexpected MQTT disconnections use the `WARNING` level. Publication and persistence failures use the `ERROR` level.

## Running the Tests

Run the complete automated test suite:

```powershell
pytest -q
```

Latest confirmed result:

```text
114 passed in 0.92s
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

Run tests with code coverage:

```powershell
pytest -v `
    --cov=device_simulator `
    --cov=fog_app `
    --cov=shared `
    --cov-report=term-missing
```

## Current Development Status

### Day 1 — Edge Sensor Simulation

Completed:

- Multi-zone sensor simulation
- Five sensor types
- Pydantic telemetry model
- MQTT QoS 1 publication
- Per-device queues
- Sequence tracking
- Reproducible simulation scenarios
- Automated testing

### Day 2 — Fog Processing

Completed:

- MQTT telemetry subscription
- Validation pipeline
- Deduplication
- Freshness validation
- Sequence validation
- Independent zone state
- Rolling sensor windows
- Deterministic risk engine
- Status and alert publication policies
- MQTT fog adapter
- SQLite persistence
- Unit and integration testing
- Real end-to-end Mosquitto validation

Confirmed repository state:

```text
Branch: feature/day2-fog-processing
Tests: 114 passed
Working tree: clean
```
