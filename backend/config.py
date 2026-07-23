"""Simple settings for the FloodGuard cloud bridge."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class BackendSettings(BaseSettings):
    """Load the cloud bridge settings from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8-sig",
        env_prefix="BACKEND_",
        extra="ignore",
    )

    aws_region: str = "us-east-1"
    sqs_queue_url: str

    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_qos: int = 1

    mqtt_status_topic: str = (
        "city/drainage/+/fog/status"
    )

    mqtt_alert_topic: str = (
        "city/drainage/+/fog/alert"
    )

    cloud_bridge_client_id: str = (
        "floodguard-cloud-bridge"
    )


def load_backend_settings() -> BackendSettings:
    """Return the current cloud bridge settings."""

    return BackendSettings()