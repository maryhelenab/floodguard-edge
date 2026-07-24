# FloodGuard Edge

FloodGuard Edge is a fog-assisted urban flood and drainage early-warning system built for the Fog and Edge Computing module.

The project simulates drainage sensors, processes readings at the fog layer, sends validated events to AWS, stores them in DynamoDB, exposes query endpoints through API Gateway, and displays the results in a simple responsive dashboard.

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

## Main Features

- Simulated rainfall, water-level, flow-rate, soil-saturation and drain-blockage sensors
- MQTT communication between sensors and the fog layer
- Local fog processing and risk assessment
- Local buffering when cloud communication is unavailable
- Validated cloud event models
- Amazon SQS event ingestion
- Dead-letter queue with a maximum receive count of 3
- AWS Lambda ingestion and query functions
- DynamoDB event storage
- API Gateway HTTP endpoints
- Responsive monitoring dashboard
- Manual and automatic dashboard refresh
- Independent zone loading with `Promise.allSettled()`
- Automated unit and integration tests

## AWS Resources

| Resource | Name |
|---|---|
| SQS queue | `floodguard-events` |
| Dead-letter queue | `floodguard-events-dlq` |
| DynamoDB table | `FloodGuardEvents` |
| Ingestion Lambda | `floodguard-ingestion` |
| Query Lambda | `floodguard-query` |
| HTTP API | `floodguard-api` |

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
| GET | `/zones/{zone_id}/latest` | Get the latest zone status |
| GET | `/zones/{zone_id}/history?limit=20` | Get recent zone history |
| GET | `/zones/{zone_id}/alerts?limit=20` | Get recent alerts |

Example zone IDs:

```text
dublin-zone-01
dublin-zone-02
dublin-zone-03
dublin-zone-04
```

## Dashboard

The `dashboard` folder contains a simple responsive dashboard built with plain HTML, CSS, JavaScript and Chart.js.

It displays:

- Four Dublin monitoring zones
- Current risk level and risk score
- Latest sensor readings
- Risk reasons
- Recommended action
- Risk-score history
- Rainfall history
- Water-level history
- Recent alerts
- API status and last-update time

No AWS credentials are stored in the browser. The dashboard calls the public API only.

### Start the dashboard

From the repository root:

```powershell
.\.venv\Scripts\Activate.ps1
python -m http.server 8080 --directory dashboard
```

Open:

```text
http://localhost:8080
```

## Project Structure

```text
floodguard-edge/
|-- backend/                 # Cloud event models and AWS Lambda functions
|-- dashboard/               # HTML, CSS and JavaScript dashboard
|-- data/                    # Local data files
|-- device_simulator/        # Simulated drainage sensors
|-- docs/                    # Architecture and project documentation
|-- fog_app/                 # Fog processing and MQTT logic
|-- infrastructure/          # AWS infrastructure files
|-- shared/                  # Shared models and utilities
|-- tests/                   # Automated tests
|-- requirements.txt         # Python dependencies
|-- docker-compose.yml       # Local service configuration
|-- .env.example             # Environment variable example
`-- README.md
```

## Local Setup

### Requirements

- Python 3
- PowerShell
- Mosquitto MQTT broker
- AWS credentials only when running cloud deployment or cloud bridge components
- Internet access for the dashboard API and Chart.js

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

Copy the example environment file:

```powershell
Copy-Item .env.example .env
```

Update `.env` only with the values required by the component being executed.

Do not commit:

- AWS access keys
- AWS secret keys
- Session tokens
- Passwords
- Private endpoints

## Testing

Run the complete automated test suite:

```powershell
pytest -q
```

Latest verified result:

```text
152 passed
```

## Risk Levels

The fog layer produces one of the following risk levels:

```text
INITIALISING
NORMAL
WATCH
WARNING
HIGH
CRITICAL
```

The risk assessment is based on the latest sensor values, recent trends and derived drainage metrics.

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

- Fog-side processing for low-latency decisions
- Local buffering during temporary network failure
- SQS-based asynchronous cloud ingestion
- A dead-letter queue for failed messages
- Partial SQS batch failure reporting
- Validation before cloud persistence
- Independent dashboard requests so one failed zone does not stop the others

## Security

- No AWS credentials are included in the frontend
- Secrets are excluded from source control
- API responses are rendered with safe DOM text operations
- Input events are validated before persistence
- IAM permissions should follow the principle of least privilege

## Troubleshooting

### Dashboard does not open

Confirm the local server is running:

```powershell
python -m http.server 8080 --directory dashboard
```

Then open:

```text
http://localhost:8080
```

### API shows as unavailable

Test the health endpoint in a browser:

```text
https://igsjnvt205.execute-api.us-east-1.amazonaws.com/health
```

Also check the browser developer console for network or CORS errors.

### Charts do not appear

Confirm that:

- Internet access is available
- Chart.js loaded successfully
- The selected zone has history records
- The browser console contains no JavaScript errors

### Tests fail

Confirm the virtual environment is active and reinstall the dependencies:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest -q
```

## Academic Context

This project demonstrates the use of fog and edge computing for a scalable urban flood-monitoring scenario. Local fog processing supports fast risk detection, while AWS services provide scalable ingestion, persistence, querying and remote monitoring.

## Author

Maryhelen Albuquerque Bastos  
MSc in Cloud Computing  
National College of Ireland
