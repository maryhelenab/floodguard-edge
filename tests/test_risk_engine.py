"""Tests for deterministic FloodGuard risk calculations."""

from dataclasses import replace

import pytest

from fog_app.config.settings import load_fog_config
from fog_app.processing.risk_engine import (
    RiskInputs,
    calculate_drainage_metrics,
    calculate_flood_risk,
    classify_risk_score,
)


def risk_settings():
    """Return the validated default risk configuration."""

    return load_fog_config().risk


def scaled_inputs(fraction: float) -> RiskInputs:
    """Create inputs whose normalised components share one fraction."""

    return RiskInputs(
        water_level_cm=80.0 * fraction,
        rainfall_mm_h=75.0 * fraction,
        water_rise_cm_min=10.0 * fraction,
        drain_blockage_percent=80.0 * fraction,
        soil_saturation_percent=90.0 * fraction,
        flow_rate_l_s=30.0 * fraction,
    )


def test_low_flow_and_low_blockage_produce_low_stress() -> None:
    """Produce low drainage stress under normal conditions."""

    metrics = calculate_drainage_metrics(
        flow_rate_l_s=3.0,
        drain_blockage_percent=10.0,
        flow_capacity_l_s=30.0,
    )

    assert metrics.flow_utilisation_percent == pytest.approx(10.0)
    assert metrics.drainage_stress_score == pytest.approx(10.0)


def test_near_capacity_flow_produces_high_stress() -> None:
    """Represent high pressure when flow approaches capacity."""

    metrics = calculate_drainage_metrics(
        flow_rate_l_s=29.0,
        drain_blockage_percent=10.0,
        flow_capacity_l_s=30.0,
    )

    assert metrics.flow_utilisation_percent == pytest.approx(
        96.67,
        abs=0.01,
    )
    assert metrics.drainage_stress_score == pytest.approx(
        96.67,
        abs=0.01,
    )


def test_high_blockage_and_low_flow_produce_high_stress() -> None:
    """Detect blocked underperformance despite low measured flow."""

    metrics = calculate_drainage_metrics(
        flow_rate_l_s=3.0,
        drain_blockage_percent=90.0,
        flow_capacity_l_s=30.0,
    )

    assert metrics.drainage_stress_score == pytest.approx(81.0)


@pytest.mark.parametrize(
    ("score", "expected_level"),
    [
        (0.0, "NORMAL"),
        (29.99, "NORMAL"),
        (30.0, "WATCH"),
        (49.99, "WATCH"),
        (50.0, "WARNING"),
        (69.99, "WARNING"),
        (70.0, "HIGH"),
        (84.99, "HIGH"),
        (85.0, "CRITICAL"),
        (100.0, "CRITICAL"),
    ],
)
def test_classifies_unambiguous_threshold_boundaries(
    score: float,
    expected_level: str,
) -> None:
    """Classify exact threshold boundaries without gaps."""

    settings = risk_settings()

    assert (
        classify_risk_score(
            score,
            settings.level_thresholds,
        )
        == expected_level
    )


@pytest.mark.parametrize(
    ("fraction", "expected_level"),
    [
        (0.10, "NORMAL"),
        (0.35, "WATCH"),
        (0.55, "WARNING"),
        (0.75, "HIGH"),
        (0.90, "CRITICAL"),
    ],
)
def test_scaled_conditions_produce_each_risk_level(
    fraction: float,
    expected_level: str,
) -> None:
    """Produce all configured levels from deterministic inputs."""

    assessment = calculate_flood_risk(
        scaled_inputs(fraction),
        risk_settings(),
    )

    assert assessment.risk_level == expected_level
    assert assessment.reasons


@pytest.mark.parametrize(
    ("field_name", "elevated_value"),
    [
        ("water_level_cm", 80.0),
        ("rainfall_mm_h", 75.0),
        ("water_rise_cm_min", 10.0),
        ("drain_blockage_percent", 80.0),
        ("soil_saturation_percent", 90.0),
        ("flow_rate_l_s", 30.0),
    ],
)
def test_each_input_component_increases_risk_score(
    field_name: str,
    elevated_value: float,
) -> None:
    """Ensure every sensor and the water-rise metric influence risk."""

    baseline_inputs = RiskInputs(
        rainfall_mm_h=0.0,
        water_level_cm=0.0,
        flow_rate_l_s=0.0,
        soil_saturation_percent=0.0,
        drain_blockage_percent=0.0,
        water_rise_cm_min=0.0,
    )

    baseline = calculate_flood_risk(
        baseline_inputs,
        risk_settings(),
    )

    elevated_inputs = replace(
        baseline_inputs,
        **{field_name: elevated_value},
    )

    elevated = calculate_flood_risk(
        elevated_inputs,
        risk_settings(),
    )

    assert elevated.risk_score > baseline.risk_score


def test_risk_score_remains_between_zero_and_one_hundred() -> None:
    """Clamp extreme measurements to the supported score range."""

    assessment = calculate_flood_risk(
        RiskInputs(
            rainfall_mm_h=1000.0,
            water_level_cm=1000.0,
            flow_rate_l_s=1000.0,
            soil_saturation_percent=1000.0,
            drain_blockage_percent=1000.0,
            water_rise_cm_min=1000.0,
        ),
        risk_settings(),
    )

    assert assessment.risk_score == 100.0
    assert assessment.risk_level == "CRITICAL"


def test_negative_water_rise_does_not_reduce_other_components() -> None:
    """Treat falling water as zero for the water-rise risk component."""

    falling = calculate_flood_risk(
        RiskInputs(
            rainfall_mm_h=30.0,
            water_level_cm=30.0,
            flow_rate_l_s=10.0,
            soil_saturation_percent=40.0,
            drain_blockage_percent=20.0,
            water_rise_cm_min=-5.0,
        ),
        risk_settings(),
    )

    stable = calculate_flood_risk(
        RiskInputs(
            rainfall_mm_h=30.0,
            water_level_cm=30.0,
            flow_rate_l_s=10.0,
            soil_saturation_percent=40.0,
            drain_blockage_percent=20.0,
            water_rise_cm_min=0.0,
        ),
        risk_settings(),
    )

    assert falling.risk_score == stable.risk_score
    assert falling.component_scores["water_rise_rate"] == 0.0


@pytest.mark.parametrize(
    ("inputs", "expected_level", "reason_fragment"),
    [
        (
            RiskInputs(
                rainfall_mm_h=0.0,
                water_level_cm=80.0,
                flow_rate_l_s=0.0,
                soil_saturation_percent=0.0,
                drain_blockage_percent=0.0,
                water_rise_cm_min=0.0,
            ),
            "CRITICAL",
            "Water level reached",
        ),
        (
            RiskInputs(
                rainfall_mm_h=0.0,
                water_level_cm=60.0,
                flow_rate_l_s=0.0,
                soil_saturation_percent=0.0,
                drain_blockage_percent=70.0,
                water_rise_cm_min=0.0,
            ),
            "CRITICAL",
            "High water level combined",
        ),
        (
            RiskInputs(
                rainfall_mm_h=0.0,
                water_level_cm=0.0,
                flow_rate_l_s=0.0,
                soil_saturation_percent=0.0,
                drain_blockage_percent=0.0,
                water_rise_cm_min=10.0,
            ),
            "HIGH",
            "Rapid water-level rise",
        ),
        (
            RiskInputs(
                rainfall_mm_h=70.0,
                water_level_cm=0.0,
                flow_rate_l_s=0.0,
                soil_saturation_percent=90.0,
                drain_blockage_percent=0.0,
                water_rise_cm_min=0.0,
            ),
            "HIGH",
            "Heavy rainfall combined with saturated soil",
        ),
        (
            RiskInputs(
                rainfall_mm_h=70.0,
                water_level_cm=0.0,
                flow_rate_l_s=0.0,
                soil_saturation_percent=0.0,
                drain_blockage_percent=75.0,
                water_rise_cm_min=0.0,
            ),
            "CRITICAL",
            "Heavy rainfall combined with severe drain blockage",
        ),
    ],
)
def test_safety_overrides_apply_minimum_levels(
    inputs: RiskInputs,
    expected_level: str,
    reason_fragment: str,
) -> None:
    """Apply configured safety overrides and explain the result."""

    assessment = calculate_flood_risk(
        inputs,
        risk_settings(),
    )

    assert assessment.risk_level == expected_level
    assert any(
        reason_fragment in reason
        for reason in assessment.reasons
    )


def test_same_inputs_produce_deterministic_result() -> None:
    """Return the same result for repeated identical calculations."""

    inputs = scaled_inputs(0.55)
    settings = risk_settings()

    first_result = calculate_flood_risk(inputs, settings)
    second_result = calculate_flood_risk(inputs, settings)

    assert first_result == second_result