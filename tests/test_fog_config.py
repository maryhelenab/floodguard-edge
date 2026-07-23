""" Tests for the FloodGuard fog-node configuration file. """
import json
from pathlib import Path
import pytest
from pydantic import ValidationError

from fog_app.config.settings import (
    DEFAULT_CONFIG_PATH,
    load_fog_config,
)

def test_load_default_fog_config() -> None:
    """ Test loading the default fog-node configuration file. """

    config = load_fog_config()

    assert config.fog_node_id == 'fog-node-dublin-01'
    assert config.zones == [
        'dublin-zone-01',
        'dublin-zone-02',
        'dublin-zone-03',
        'dublin-zone-04'
    ]
    assert config.mqtt.qos == 1
    assert config.mqtt.telemetry_subscription_topic == (
        'city/drainage/+/+/telemetry'
    )

def test_rejects_risk_weights_that_do_not_sum_to_1(tmp_path: Path,) -> None:
    """ Test that the fog-node configuration file rejects risk weights that do not sum to 1. """

    raw_config = json.loads(
        DEFAULT_CONFIG_PATH.read_text(encoding='utf-8')
    )

    # Increase one weight so the total becomes invalid.
    raw_config['risk']['weights']['water_level'] = 0.40

    invalid_config_path = tmp_path / 'invalid_fog_config.json'
    invalid_config_path.write_text(
        json.dumps(raw_config),
        encoding='utf-8'
    )

    with pytest.raises(
        ValidationError,
        match=r"Risk weights must sum to 1\.0"
    ):
        load_fog_config(invalid_config_path)
