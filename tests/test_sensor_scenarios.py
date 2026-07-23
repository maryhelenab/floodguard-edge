"""Generate a reproducible rainfall series for one scenario."""
import random
from unittest.mock import patch
from device_simulator.sensor import generate_sensor_value, load_config

def generate_rainfall_series(
        config: dict, scenario: str) -> list[float]:
    """Generate a series of rainfall values based on the configuration and sensor type."""
    config["simulation"]["scenario"] = scenario

    random.seed(config["simulation"]["random_seed"])

    return [
        generate_sensor_value(
            config=config,
            sensor_type="rainfall",
            sequence=sequence
        ) for sequence in range(
            1,
            config["simulation"]["readings_per_sensor"] + 1
            )
    ]

def test_normal_scenario_is_reproducible() -> None:
    """Test same seed should generate the same normal scenario values."""
    config = load_config()

    series1 = generate_rainfall_series(config, "normal")
    series2 = generate_rainfall_series(config, "normal")

    assert series1 == series2

def test_developing_flood_increases_final_rainfall() -> None:
    """Test that the developing flood scenario increases rainfall values."""
    config = load_config()

    normal_series = generate_rainfall_series(config, "normal")
    developing_flood_series = generate_rainfall_series(
        config,
        "developing_flood"
        )

    assert developing_flood_series[0] == normal_series[0], "Initial values should be the same"
    assert developing_flood_series[-1] > normal_series[-1], "Final value should be higher in developing flood scenario"

def test_developing_flood_flow_rate_peaks_then_declines() -> None:
    """Flow rate should peak and then decline as blockage develops."""
    config = load_config()
    config["simulation"]["scenario"] = "developing_flood"

    with patch(
        "device_simulator.sensor.random.uniform",
        return_value=10.0,
    ):
        flow_values = [
            generate_sensor_value(
                config=config,
                sensor_type="flow_rate",
                sequence=sequence
            ) for sequence in range(
                1,
                6
            )
        ]

    assert flow_values == [10.0, 14.0, 18.0, 16.0, 14.0]

def test_developing_flood_water_level_rises_faster_late() -> None:
    """Water level should rise more rapidly near the end of the flood."""
    config = load_config()
    config["simulation"]["scenario"] = "developing_flood"

    with patch(
        "device_simulator.sensor.random.uniform",
        return_value=10.0,
    ):
        water_levels = [
            generate_sensor_value(
                config=config,
                sensor_type="water_level",
                sequence=sequence
            ) for sequence in range(
                1,
                6
            )
        ]

    assert water_levels == [10.0, 10.62, 12.5, 15.62, 20.0]

def test_developing_flood_drain_blockage_accelerates() -> None:
    """Drain blockage should grow faster near the end of the flood."""
    config = load_config()
    config["simulation"]["scenario"] = "developing_flood"

    with patch(
        "device_simulator.sensor.random.uniform",
        return_value=10.0,
    ):
        blockage_values = [
            generate_sensor_value(
                config=config,
                sensor_type="drain_blockage",
                sequence=sequence
            ) for sequence in range(
                1,
                6
            )
        ]

    early_increase = blockage_values[1] - blockage_values[0]
    late_increase = blockage_values[-1] - blockage_values[-2]

    assert blockage_values[-1] > blockage_values[0], "Blockage should increase over time"
    assert late_increase > early_increase, "Blockage should increase faster later in the flood"