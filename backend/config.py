"""Environment-based settings for the MQTT-to-SQS cloud bridge."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class BackendSettings(BaseSettings):
    """Load and validate cloud-bridge settings from the environment."""

    # Values can be placed in .env during local development.  The prefix means
    # ``aws_region`` is read from ``BACKEND_AWS_REGION``, for example.
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8-sig",
        env_prefix="BACKEND_",
        extra="ignore",
    )

    # AWS destination used by the bridge.
    aws_region: str = "us-east-1"
    sqs_queue_url: str

    # Local MQTT broker connection.
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_qos: int = 1

    # The + wildcard subscribes to every configured drainage zone.
    mqtt_status_topic: str = "city/drainage/+/fog/status"
    mqtt_alert_topic: str = "city/drainage/+/fog/alert"

    # A stable client ID helps the broker identify this bridge process.
    cloud_bridge_client_id: str = "floodguard-cloud-bridge"


def load_backend_settings() -> BackendSettings:
    """Build and return the validated backend configuration."""

    return BackendSettings()
