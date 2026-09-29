"""Request contract for the single-hour energy prediction.

Kept in its own module for the same reason its route is: the feature is additive, and
deleting this file plus its route and one registration line removes it completely without
touching the analysis contracts in ``schemas.models``.

The one field that needs explaining is ``target_datetime``. It is the hour the caller wants
an answer *for* — which is a different thing from the ``start_date``/``end_date`` of an
analysis, and the distinction is the whole reason this endpoint exists. Those two bound the
period the model is *trained* on; this one names the hour it is asked about. Everything the
model sees is drawn from strictly before it.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.models import LocationInput, PVSystemInput


class PointForecastRequest(BaseModel):
    """Predict the energy a declared array produces in one specific hour."""

    model_config = ConfigDict(extra="forbid")

    location: LocationInput
    target_datetime: datetime = Field(
        description=(
            "The local date and hour to predict, ISO 8601 — for example "
            "'2025-06-14T14:00'. Read in the location's own time zone when no offset is "
            "given. Minutes are ignored: the archive is hourly on UTC hours, so the value "
            "is floored to the hour in UTC and the resolved hour is echoed back in both "
            "local and UTC form. In a zone offset by half an hour the resolved local time "
            "therefore ends in :30."
        )
    )
    system: PVSystemInput = Field(default_factory=PVSystemInput)
    model_key: str = Field(
        default="xgboost_plants",
        max_length=64,
        description="Defaults to the project's XGBoost model trained on measured plant output.",
    )
    nominal_coverage: float = Field(default=0.8, ge=0.5, le=0.99)

    @field_validator("model_key")
    @classmethod
    def _known_model(cls, v: str) -> str:
        from app.models import registry

        if v != "xgboost_plants" and v not in registry.MODELS:
            raise ValueError(
                f"Unknown model '{v}'. Available models: {', '.join(sorted(registry.MODELS))}."
            )
        return v

    @field_validator("target_datetime")
    @classmethod
    def _plausible_year(cls, v: datetime) -> datetime:
        # A crude bound only. Whether the hour is actually covered depends on how far the
        # reanalysis archive currently extends, which is a runtime fact, so the real check
        # lives in the route where it can name the exact window that is available.
        if not 1940 <= v.year <= 2100:
            raise ValueError(
                f"target_datetime has year {v.year}, which is outside any period this "
                f"platform holds data for."
            )
        return v
