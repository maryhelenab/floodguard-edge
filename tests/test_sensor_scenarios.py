"""Generate a reproducible rainfall series for one scenario."""
import random
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