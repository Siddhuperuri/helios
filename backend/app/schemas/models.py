"""Typed request and response contracts.

Validation happens here, at the boundary, before any expensive work is scheduled. Two
concerns are served at once: scientifically meaningless requests are rejected with an
explanation the user can act on, and the amount of computation an unauthenticated caller
can trigger is bounded.

Error messages name the offending field, the value received and the accepted range. A
message like "Something went wrong" is treated as a defect.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.config import get_settings

_LIMITS = get_settings().limits


class LocationInput(BaseModel):
    """Either a place name or an explicit coordinate pair."""

    model_config = ConfigDict(extra="forbid")

    query: str | None = Field(
        default=None, max_length=120, description="Place name, e.g. 'Hyderabad, India'."
    )
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)

    @model_validator(mode="after")
    def _require_one(self) -> LocationInput:
        has_coords = self.latitude is not None and self.longitude is not None
        has_query = bool(self.query and self.query.strip())
        if not has_coords and not has_query:
            raise ValueError(
                "Provide either 'query' (a place name) or both 'latitude' and 'longitude'."
            )
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError(
                "Latitude and longitude must be supplied together; one was given without "
                "the other."
            )
        return self


class PVSystemInput(BaseModel):
    """Declared photovoltaic system.

    Every field must be stated for an energy figure in kWh to have a defined meaning.
    """

    model_config = ConfigDict(extra="forbid")

    dc_capacity_kwp: float = Field(default=5.0, gt=0.0, le=1_000_000.0)
    surface_tilt_deg: float = Field(default=20.0, ge=0.0, le=90.0)
    surface_azimuth_deg: float = Field(default=180.0, ge=0.0, lt=360.0)
    temperature_coefficient_per_c: float = Field(default=-0.0035, ge=-0.01, le=0.0)
    system_losses_fraction: float = Field(default=0.14, ge=0.0, lt=1.0)
    inverter_efficiency: float = Field(default=0.96, gt=0.0, le=1.0)
    inverter_ac_capacity_kw: float | None = Field(default=None, gt=0.0)
    albedo: float = Field(default=0.2, ge=0.0, le=1.0)


class AnalysisRequest(BaseModel):
    """Create an analysis: fetch data, assess quality, build features, train, evaluate."""

    model_config = ConfigDict(extra="forbid")

    location: LocationInput
    start_date: date | None = Field(
        default=None, description="Defaults to the configured training window before end_date."
    )
    end_date: date | None = Field(
        default=None, description="Defaults to the latest date the archive covers."
    )
    model_key: str = Field(default="random_forest", max_length=64)
    # "pv_kwh" trains the model to predict the declared array's hourly AC energy directly.
    # Its labels come from the PV chain applied to observed weather, not from a meter — see
    # app.features.pipeline.add_pv_energy.
    target: Literal["clear_sky_index", "ghi_wm2", "pv_kwh"] = "clear_sky_index"
    system: PVSystemInput = Field(default_factory=PVSystemInput)
    horizon_hours: int = Field(
        default=24, ge=_LIMITS.min_horizon_hours, le=_LIMITS.max_horizon_hours
    )
    test_fraction: float = Field(default=0.2, ge=0.05, le=0.5)
    cv_splits: int = Field(default=5, ge=2, le=10)
    nominal_coverage: float = Field(default=0.8, ge=0.5, le=0.99)
    compute_intervals: bool = True
    run_cv: bool = True
    label: str | None = Field(default=None, max_length=120)

    @field_validator("model_key")
    @classmethod
    def _known_model(cls, v: str) -> str:
        from app.models import registry

        if v not in registry.MODELS:
            raise ValueError(
                f"Unknown model '{v}'. Available models: {', '.join(sorted(registry.MODELS))}."
            )
        return v

    @model_validator(mode="after")
    def _validate_period(self) -> AnalysisRequest:
        if self.start_date and self.end_date:
            if self.start_date >= self.end_date:
                raise ValueError(
                    f"start_date ({self.start_date}) must be earlier than end_date "
                    f"({self.end_date})."
                )
            span = (self.end_date - self.start_date).days
            if span < _LIMITS.min_training_days:
                raise ValueError(
                    f"The requested period spans {span} days. At least "
                    f"{_LIMITS.min_training_days} days are required for time-aware "
                    f"cross-validation with a hold-out test set."
                )
            if span > _LIMITS.max_training_days:
                raise ValueError(
                    f"The requested period spans {span} days, above the maximum of "
                    f"{_LIMITS.max_training_days}."
                )
        return self


class ForecastRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    horizon_hours: int = Field(
        default=48, ge=_LIMITS.min_horizon_hours, le=_LIMITS.max_horizon_hours
    )
    system: PVSystemInput | None = None
    nominal_coverage: float = Field(default=0.8, ge=0.5, le=0.99)


class PerturbationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variable: str = Field(max_length=64)
    mode: Literal["delta", "scale", "set"]
    value: float

    @field_validator("value")
    @classmethod
    def _finite(cls, v: float) -> float:
        import math

        if not math.isfinite(v):
            raise ValueError("Perturbation value must be a finite number.")
        return v


class ScenarioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="Custom scenario", max_length=120)
    kind: Literal["meteorological", "system"] = "meteorological"
    perturbations: list[PerturbationInput] = Field(default_factory=list, max_length=8)
    scenario_system: PVSystemInput | None = None
    preset_key: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _needs_content(self) -> ScenarioRequest:
        if self.kind == "meteorological" and not self.perturbations and not self.preset_key:
            raise ValueError(
                "A meteorological scenario needs at least one perturbation, or a preset_key."
            )
        if self.kind == "system" and self.scenario_system is None:
            raise ValueError("A system scenario needs 'scenario_system' to compare against.")
        return self


class ModelComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_keys: list[str] = Field(min_length=2, max_length=8)

    @field_validator("model_keys")
    @classmethod
    def _known(cls, v: list[str]) -> list[str]:
        from app.models import registry

        unknown = [k for k in v if k not in registry.MODELS]
        if unknown:
            raise ValueError(
                f"Unknown model(s): {', '.join(unknown)}. Available: "
                f"{', '.join(sorted(registry.MODELS))}."
            )
        if len(set(v)) != len(v):
            raise ValueError("Duplicate model keys in the comparison request.")
        return v


class ExperimentCompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_ids: list[str] = Field(min_length=1, max_length=10)


class ErrorResponse(BaseModel):
    """Structured error payload.

    ``message`` is written for a person; ``detail`` carries diagnostics; ``remedy``
    states what to change. Internal exception text is never surfaced verbatim.
    """

    error: str
    message: str
    detail: str | None = None
    remedy: str | None = None
    field_errors: list[dict[str, Any]] | None = None
