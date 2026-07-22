# FloodGuard Edge

FloodGuard Edge is a fog-assisted urban flood and drainage early-warning system.

The project simulates environmental and drainage sensors distributed across multiple urban zones. Sensor telemetry is validated locally and published through MQTT for later processing by the fog and cloud components.

## Repository

GitHub:

https://github.com/maryhelenab/floodguard-edge

## Current Day 1 Features

The current device simulator supports:

- Four simulated urban zones
- Five sensor types
- MQTT telemetry publishing using Quality of Service level 1
- One local telemetry queue for each simulated sensor device
- Separate telemetry generation and MQTT dispatch intervals
- Unique event identifiers using UUID
- Independent sequence numbers for each sensor device
- Pydantic telemetry validation
- Structured INFO and ERROR logging
- MQTT connection error handling
- Graceful shutdown with Ctrl+C
- Deterministic simulation using a fixed random seed
- Normal and developing flood scenarios
- Correlated developing-flood sensor behaviour
- Automated testing with pytest
- 13 automated tests with 88% total code coverage

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
| Soil saturation | percent | Measures how saturated the soil is |
| Drain blockage | percent | Estimates drainage obstruction |

## Project Structure

```text
floodguard-edge/
|-- backend/
|-- dashboard/
|-- data/
|-- device_simulator/
|   |-- config.json
|   `-- sensor.py
|-- docs/
|-- fog_app/
|-- infrastructure/
|-- shared/
|   `-- telemetry.py
|-- tests/
|   |-- test_sensor_scenarios.py
|   `-- test_telemetry.py
|-- .env.example
|-- docker-compose.yml
`-- README.md

```

## Requirements

The current local simulator requires:

- Python 3.13 or compatible
- Mosquitto MQTT Broker
- Paho MQTT
- Pydantic
- Pytest

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

The simulator currently connects to a local Mosquitto broker using:

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
10. Disconnect safely after completion or when interrupted with Ctrl+C.

## MQTT Topics

Telemetry uses the following topic structure:

```text
city/drainage/{zone_id}/{sensor_type}/telemetry
```

Example:

```text
city/drainage/dublin-zone-01/rainfall/telemetry
```

Subscribe to all FloodGuard telemetry topics:

```powershell
mosquitto_sub -h localhost -p 1883 -t "city/drainage/#" -q 1 -v
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

The developing flood scenario models related sensor behaviour: rainfall increases, drain blockage accelerates, flow rate reaches a peak and then declines as drainage capacity is reduced, and water level rises more rapidly near the end of the scenario.

A fixed random seed makes the generated values reproducible during testing.

## Logging

The simulator records structured logs using this format:

```text
timestamp | log level | module | message
```

Example:

```text
2026-07-22 10:04:47,759 | INFO | __main__ | Published message 1
```

Normal operations use the `INFO` level. MQTT connection failures use the `ERROR` level.

## Running the Tests

Run the complete automated test suite:

```powershell
pytest -v
```

The current 13 automated tests verify that:

- Valid telemetry messages are accepted.
- Invalid sequence numbers are rejected.
- Each telemetry event receives a unique UUID.
- MQTT topics follow the expected structure.
- Sensor messages contain the required fields.
- One local queue is created for each simulated device.
- Queued messages are removed only after successful MQTT publication.
- The complete simulation workflow can run with a mocked MQTT client.
- Normal scenario values are reproducible.
- Developing flood rainfall increases.
- Flow rate reaches a peak and then declines.
- Water level rises more rapidly near the end.
- Drain blockage growth accelerates.

Run the test suite with code coverage:

```powershell
pytest -v --cov=device_simulator --cov=shared --cov-report=term-missing