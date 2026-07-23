"""Deterministic rule-based flood-risk calculations."""

from dataclasses import dataclass
from typing import Literal, Mapping

from fog_app.config.settings import (
    RiskLevelThresholds,
    RiskSettings,
)


RiskLevel = Literal[
    "NORMAL",
    "WATCH",
    "WARNING",
    "HIGH",
    "CRITICAL",
]

RISK_LEVEL_ORDER: dict[RiskLevel, int] = {
    "NORMAL": 0,
    "WATCH": 1,
    "WARNING": 2,
    "HIGH": 3,
    "CRITICAL": 4,
}


@dataclass(frozen=True, slots=True)
class RiskInputs:
    """Values required to calculate one zone flood-risk assessment."""

    rainfall_mm_h: float
    water_level_cm: float
    flow_rate_l_s: float
    soil_saturation_percent: float
    drain_blockage_percent: float
    water_rise_cm_min: float

    def __post_init__(self) -> None:
        """Reject physically invalid negative sensor measurements."""

        non_negative_values = {
            "rainfall_mm_h": self.rainfall_mm_h,
            "water_level_cm": self.water_level_cm,
            "flow_rate_l_s": self.flow_rate_l_s,
            "soil_saturation_percent": self.soil_saturation_percent,
            "drain_blockage_percent": self.drain_blockage_percent,
        }

        for field_name, value in non_negative_values.items():
            if value < 0:
                raise ValueError(
                    f"{field_name} cannot be negative."
                )


@dataclass(frozen=True, slots=True)
class DrainageMetrics:
    """Derived indicators describing drainage-system pressure."""

    flow_utilisation_percent: float
    drainage_stress_score: float


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    """Complete deterministic flood-risk result for one zone."""

    risk_score: float
    risk_level: RiskLevel
    component_scores: Mapping[str, float]
    flow_utilisation_percent: float
    drainage_stress_score: float
    reasons: tuple[str, ...]


def _clamp(
    value: float,
    minimum: float = 0.0,
    maximum: float = 100.0,
) -> float:
    """Limit a numeric value to an inclusive range."""

    return min(max(value, minimum), maximum)


def normalise_risk_value(
    value: float,
    critical_value: float,
) -> float:
    """Normalise a measurement to a risk component from 0 to 100."""

    if critical_value <= 0:
        raise ValueError("Critical normalisation value must be positive.")

    return _clamp(value / critical_value, 0.0, 1.0) * 100.0


def calculate_drainage_metrics(
    *,
    flow_rate_l_s: float,
    drain_blockage_percent: float,
    flow_capacity_l_s: float,
) -> DrainageMetrics:
    """Calculate flow utilisation and rule-based drainage stress.

    This is a project heuristic rather than a calibrated hydraulic model.
    It identifies either near-capacity flow or blocked underperformance.
    """

    if flow_capacity_l_s <= 0:
        raise ValueError("Flow capacity must be positive.")

    if flow_rate_l_s < 0:
        raise ValueError("Flow rate cannot be negative.")

    bounded_blockage = _clamp(
        drain_blockage_percent,
        0.0,
        100.0,
    )

    flow_utilisation = _clamp(
        flow_rate_l_s / flow_capacity_l_s,
        0.0,
        1.0,
    )

    capacity_pressure_score = flow_utilisation * 100.0

    blocked_underperformance_score = (
        bounded_blockage * (1.0 - flow_utilisation)
    )

    drainage_stress_score = _clamp(
        max(
            capacity_pressure_score,
            blocked_underperformance_score,
        )
    )

    return DrainageMetrics(
        flow_utilisation_percent=round(
            flow_utilisation * 100.0,
            2,
        ),
        drainage_stress_score=round(
            drainage_stress_score,
            2,
        ),
    )


def classify_risk_score(
    risk_score: float,
    thresholds: RiskLevelThresholds,
) -> RiskLevel:
    """Convert a bounded risk score into its configured risk level."""

    bounded_score = _clamp(risk_score)

    if bounded_score >= thresholds.critical_min:
        return "CRITICAL"

    if bounded_score >= thresholds.high_min:
        return "HIGH"

    if bounded_score >= thresholds.warning_min:
        return "WARNING"

    if bounded_score >= thresholds.watch_min:
        return "WATCH"

    return "NORMAL"


def _higher_level(
    current_level: RiskLevel,
    minimum_level: RiskLevel,
) -> RiskLevel:
    """Return the more severe of two risk levels."""

    if (
        RISK_LEVEL_ORDER[minimum_level]
        > RISK_LEVEL_ORDER[current_level]
    ):
        return minimum_level

    return current_level


def _add_reason(
    reasons: list[str],
    reason: str,
) -> None:
    """Append a reason without introducing duplicates."""

    if reason not in reasons:
        reasons.append(reason)


def calculate_flood_risk(
    inputs: RiskInputs,
    settings: RiskSettings,
) -> RiskAssessment:
    """Calculate a deterministic flood-risk assessment."""

    drainage_metrics = calculate_drainage_metrics(
        flow_rate_l_s=inputs.flow_rate_l_s,
        drain_blockage_percent=inputs.drain_blockage_percent,
        flow_capacity_l_s=settings.flow_capacity_l_s,
    )

    normalisation = settings.normalisation

    component_scores = {
        "water_level": normalise_risk_value(
            inputs.water_level_cm,
            normalisation.water_level_critical_cm,
        ),
        "rainfall": normalise_risk_value(
            inputs.rainfall_mm_h,
            normalisation.rainfall_critical_mm_h,
        ),
        "water_rise_rate": normalise_risk_value(
            max(inputs.water_rise_cm_min, 0.0),
            normalisation.water_rise_rate_critical_cm_min,
        ),
        "drain_blockage": normalise_risk_value(
            inputs.drain_blockage_percent,
            normalisation.drain_blockage_critical_percent,
        ),
        "soil_saturation": normalise_risk_value(
            inputs.soil_saturation_percent,
            normalisation.soil_saturation_critical_percent,
        ),
        "drainage_stress": normalise_risk_value(
            drainage_metrics.drainage_stress_score,
            normalisation.drainage_stress_critical,
        ),
    }

    weights = settings.weights

    weighted_score = (
        component_scores["water_level"] * weights.water_level
        + component_scores["rainfall"] * weights.rainfall
        + component_scores["water_rise_rate"]
        * weights.water_rise_rate
        + component_scores["drain_blockage"]
        * weights.drain_blockage
        + component_scores["soil_saturation"]
        * weights.soil_saturation
        + component_scores["drainage_stress"]
        * weights.drainage_stress
    )

    bounded_score = _clamp(weighted_score)

    risk_level = classify_risk_score(
        bounded_score,
        settings.level_thresholds,
    )

    reasons: list[str] = []
    overrides = settings.overrides

    def apply_override(
        minimum_level: RiskLevel,
        reason: str,
    ) -> None:
        """Apply a minimum safety level and record its explanation."""

        nonlocal risk_level

        risk_level = _higher_level(
            risk_level,
            minimum_level,
        )
        _add_reason(reasons, reason)

    if inputs.water_level_cm >= overrides.water_level_critical_cm:
        apply_override(
            "CRITICAL",
            "Water level reached the critical threshold.",
        )

    if (
        inputs.water_level_cm
        >= overrides.combined_water_level_critical_cm
        and inputs.drain_blockage_percent
        >= overrides.combined_blockage_critical_percent
    ):
        apply_override(
            "CRITICAL",
            "High water level combined with severe drain blockage.",
        )

    if (
        inputs.water_rise_cm_min
        >= overrides.rapid_rise_high_cm_min
    ):
        apply_override(
            "HIGH",
            "Rapid water-level rise detected.",
        )

    if (
        inputs.rainfall_mm_h
        >= overrides.heavy_rainfall_high_mm_h
        and inputs.soil_saturation_percent
        >= overrides.soil_saturation_high_percent
    ):
        apply_override(
            "HIGH",
            "Heavy rainfall combined with saturated soil.",
        )

    if (
        inputs.rainfall_mm_h
        >= overrides.heavy_rainfall_critical_mm_h
        and inputs.drain_blockage_percent
        >= overrides.blockage_critical_percent
    ):
        apply_override(
            "CRITICAL",
            "Heavy rainfall combined with severe drain blockage.",
        )

    if component_scores["water_level"] >= 50.0:
        _add_reason(
            reasons,
            "Water level is elevated relative to the configured critical value.",
        )

    if component_scores["rainfall"] >= 50.0:
        _add_reason(
            reasons,
            "Rainfall intensity is increasing surface-water input.",
        )

    if component_scores["water_rise_rate"] >= 50.0:
        _add_reason(
            reasons,
            "Water level is rising rapidly.",
        )

    if component_scores["drain_blockage"] >= 50.0:
        _add_reason(
            reasons,
            "Drain blockage is restricting effective drainage.",
        )

    if component_scores["soil_saturation"] >= 50.0:
        _add_reason(
            reasons,
            "Soil saturation is increasing surface-runoff risk.",
        )

    if drainage_metrics.flow_utilisation_percent >= 80.0:
        _add_reason(
            reasons,
            "Drain flow is operating near configured capacity.",
        )

    if (
        inputs.drain_blockage_percent >= 70.0
        and drainage_metrics.flow_utilisation_percent < 50.0
    ):
        _add_reason(
            reasons,
            "Severe blockage is reducing effective drainage flow.",
        )

    if not reasons:
        if risk_level == "NORMAL":
            reasons.append(
                "Current sensor conditions remain within the configured normal range."
            )
        else:
            reasons.append(
                "Combined sensor conditions produced an elevated flood-risk score."
            )

    rounded_components = {
        name: round(score, 2)
        for name, score in component_scores.items()
    }

    return RiskAssessment(
        risk_score=round(bounded_score, 2),
        risk_level=risk_level,
        component_scores=rounded_components,
        flow_utilisation_percent=(
            drainage_metrics.flow_utilisation_percent
        ),
        drainage_stress_score=(
            drainage_metrics.drainage_stress_score
        ),
        reasons=tuple(reasons),
    )