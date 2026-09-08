"""Request contracts for the consumer estimate.

Validation is deliberately permissive about *presence* and strict about *values*. Almost
every field is optional, because §8 and §12 require the estimate to run on whatever the
user could answer — but anything that is supplied has to be physically possible, and the
message that comes back when it is not has to say what to change (§30).

Contrast with :mod:`app.schemas.models`, which serves the research surface and requires a
fully declared system before it will produce a kWh figure. Both stances are right for their
audience: a researcher must not get an energy number from undeclared inputs, and a farmer
must not be blocked from an estimate because they do not know their inverter's efficiency.
The difference between the two is carried by the assumptions ledger, which records exactly
which values the user gave and which the platform chose.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

UserTypeLiteral = Literal["home", "farm", "shop", "commercial", "institution", "exploring"]
ModeLiteral = Literal["quick", "detailed"]
# What the user came to do. Decides whether panel count is an input or an output.
GoalLiteral = Literal["existing", "install", "compare"]
ConsumptionMethod = Literal["bill", "units", "equipment", "floor_area", "unknown"]
InstallationType = Literal[
    "rooftop", "ground_mounted", "farm_land", "parking_structure", "mixed", "not_sure"
]
ShadingLevel = Literal["none", "light", "moderate", "heavy", "unknown"]


class LocationSpec(BaseModel):
    """Where the system will be. Three ways in, per §9."""

    model_config = ConfigDict(extra="forbid")

    query: str | None = Field(default=None, max_length=160)
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)

    @model_validator(mode="after")
    def _one_of(self) -> LocationSpec:
        has_coords = self.latitude is not None and self.longitude is not None
        has_query = bool(self.query and self.query.strip())
        if not has_coords and not has_query:
            raise ValueError(
                "Tell us where you are — search for a place, use your current location, or "
                "pick a point on the map."
            )
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError(
                "A map point needs both a latitude and a longitude; only one was given."
            )
        return self


class EquipmentEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(max_length=64)
    count: float = Field(default=1, gt=0, le=10_000)
    hours_per_day: float | None = Field(default=None, ge=0, le=24)
    days_per_month: int | None = Field(default=None, ge=0, le=31)
    watts: float | None = Field(default=None, gt=0, le=1_000_000)


class PumpEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    horsepower: float = Field(gt=0, le=500)
    count: float = Field(default=1, gt=0, le=1_000)
    hours_per_day: float = Field(default=6, ge=0, le=24)
    days_per_month: int = Field(default=26, ge=0, le=31)
    motor_efficiency: float | None = Field(default=None, ge=0.2, le=1.0)


class AreaSpec(BaseModel):
    """Available space, however the user chose to express it (§13)."""

    model_config = ConfigDict(extra="forbid")

    value: float | None = Field(default=None, gt=0, le=100_000_000)
    unit: str = Field(default="sqm", max_length=20)
    length: float | None = Field(default=None, gt=0, le=100_000)
    width: float | None = Field(default=None, gt=0, le=100_000)
    dimension_unit: str = Field(default="m", max_length=10)
    polygon: list[tuple[float, float]] | None = Field(default=None, max_length=200)

    @field_validator("polygon")
    @classmethod
    def _polygon_shape(cls, v: list[tuple[float, float]] | None):
        if v is None:
            return v
        if len(v) < 3:
            raise ValueError(
                "An area drawn on the map needs at least three corners. Add another point."
            )
        for lat, lon in v:
            if not -90 <= lat <= 90 or not -180 <= lon <= 180:
                raise ValueError("The drawn area contains a point that is not on the map.")
        return v


class BatterySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    wanted: bool = False
    capacity_kwh: float | None = Field(default=None, gt=0, le=100_000)
    desired_backup_hours: float | None = Field(default=None, gt=0, le=72)
    critical_load_kw: float | None = Field(default=None, gt=0, le=10_000)
    grid_connected: bool = True


class SystemSpec(BaseModel):
    """Everything about the array. All optional — §14 forbids requiring any of it."""

    model_config = ConfigDict(extra="forbid")

    capacity_kwp: float | None = Field(default=None, gt=0, le=1_000_000)
    # Panel count and rating. For an existing array these are the measurement the whole
    # estimate is built on; for a new one they are the recommendation, overridable.
    panel_count: int | None = Field(default=None, gt=0, le=1_000_000)
    panel_watts: int | None = Field(default=None, ge=50, le=1_000)
    panel_model: str | None = Field(default=None, max_length=120)
    # Datasheet dimensions. Optional: panel area is otherwise derived from rating and
    # efficiency, which reproduces real datasheets to about one per cent.
    panel_length_m: float | None = Field(default=None, gt=0.1, le=5.0)
    panel_width_m: float | None = Field(default=None, gt=0.1, le=5.0)
    # Datasheet electricals (§14). Recorded and displayed, never invented: they depend on
    # cell count and chemistry this platform does not hold for any specific product.
    panel_voc: float | None = Field(default=None, gt=0, le=2000)
    panel_isc: float | None = Field(default=None, gt=0, le=100)
    panel_vmp: float | None = Field(default=None, gt=0, le=2000)
    panel_imp: float | None = Field(default=None, gt=0, le=100)
    panel_key: str = Field(default="mono_perc", max_length=64)
    tilt_deg: float | None = Field(default=None, ge=0, le=90)
    azimuth_deg: float | None = Field(default=None, ge=0, lt=360)
    shading_level: ShadingLevel = "unknown"
    inverter_efficiency: float | None = Field(default=None, gt=0.5, le=1.0)
    inverter_ac_capacity_kw: float | None = Field(default=None, gt=0, le=1_000_000)
    dc_ac_ratio: float | None = Field(default=None, ge=0.8, le=2.0)
    degradation_rate: float | None = Field(default=None, ge=0.0, le=0.05)
    lifetime_years: int | None = Field(default=None, ge=5, le=40)
    loss_overrides: dict[str, float] = Field(default_factory=dict)

    @field_validator("panel_key")
    @classmethod
    def _known_panel(cls, v: str) -> str:
        from app.estimate import assumptions as A

        if v not in A.PANEL_TECHNOLOGIES:
            raise ValueError(
                f"'{v}' is not a panel type we hold. Available: "
                f"{', '.join(sorted(A.PANEL_TECHNOLOGIES))}."
            )
        return v

    @field_validator("loss_overrides")
    @classmethod
    def _valid_losses(cls, v: dict[str, float]) -> dict[str, float]:
        from app.estimate import assumptions as A

        known = {item.key for item in A.DEFAULT_LOSS_STACK}
        for key, value in v.items():
            if key not in known:
                raise ValueError(
                    f"'{key}' is not a loss we model. Available: {', '.join(sorted(known))}."
                )
            if not 0.0 <= value < 1.0:
                raise ValueError(
                    f"The loss '{key}' must be between 0 and 1 (as a fraction); got {value}."
                )
        return v


class OperationsSpec(BaseModel):
    """How the site runs. Only the commercial and institutional flows collect this."""

    model_config = ConfigDict(extra="forbid")

    operating_hours: float | None = Field(default=None, gt=0, le=24)
    peak_demand_kw: float | None = Field(default=None, gt=0, le=1_000_000)
    connected_load_kw: float | None = Field(default=None, gt=0, le=1_000_000)
    # What share of consumption the system should aim to cover. Feeds sizing directly.
    offset_target_pct: float | None = Field(default=None, gt=0, le=200)
    grid_connection: Literal["net_metering", "no_export", "off_grid"] | None = None
    # What the persona is powering: a farm's loads, a shop's trade, a facility's type.
    farm_loads: list[str] = Field(default_factory=list, max_length=12)
    business_type: str | None = Field(default=None, max_length=40)
    facility_type: str | None = Field(default=None, max_length=40)


class MoneySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tariff_per_kwh: float | None = Field(default=None, gt=0, le=1_000)
    fixed_monthly_charge: float | None = Field(default=None, ge=0, le=1_000_000)
    export_rate_per_kwh: float | None = Field(default=None, ge=0, le=1_000)
    budget: float | None = Field(default=None, gt=0)
    system_cost: float | None = Field(default=None, gt=0)


class FarmSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pump_horsepower: float | None = Field(default=None, gt=0, le=500)
    pump_head_metres: float | None = Field(default=None, gt=0, le=1_000)
    required_daily_water_m3: float | None = Field(default=None, gt=0, le=1_000_000)
    crop_water_mm_per_day: float | None = Field(default=None, gt=0, le=100)


class EstimateRequest(BaseModel):
    """One request, one complete answer."""

    model_config = ConfigDict(extra="forbid")

    user_type: UserTypeLiteral = "exploring"
    mode: ModeLiteral = "quick"
    goal: GoalLiteral = "install"
    # The one genuinely required input. Pydantic's own "Field required" is accurate and
    # useless to a person, so the message says what to do instead (§30).
    location: LocationSpec = Field(
        description=(
            "Where the system will be. Search for a place, share your current location, "
            "or pick a point on the map."
        ),
    )

    consumption_method: ConsumptionMethod | None = None
    monthly_bill: float | None = Field(default=None, gt=0, le=100_000_000)
    monthly_kwh: float | None = Field(default=None, gt=0, le=100_000_000)
    equipment: list[EquipmentEntry] = Field(default_factory=list, max_length=60)
    pumps: list[PumpEntry] = Field(default_factory=list, max_length=30)
    floor_area_m2: float | None = Field(default=None, gt=0, le=10_000_000)
    occupants: int | None = Field(default=None, gt=0, le=1_000_000)

    installation_type: InstallationType = "not_sure"
    area: AreaSpec | None = None

    system: SystemSpec = Field(default_factory=SystemSpec)
    battery: BatterySpec = Field(default_factory=BatterySpec)
    money: MoneySpec = Field(default_factory=MoneySpec)
    operations: OperationsSpec = Field(default_factory=OperationsSpec)
    farm: FarmSpec = Field(default_factory=FarmSpec)

    export_allowed: bool = True
    history_years: int = Field(default=3, ge=1, le=10)
    label: str | None = Field(default=None, max_length=120)
    save: bool = True

    @model_validator(mode="after")
    def _consumption_consistent(self) -> EstimateRequest:
        method = self.consumption_method
        if method == "bill" and self.monthly_bill is None:
            raise ValueError(
                "You chose to enter your electricity bill, but no amount was given."
            )
        if method == "units" and self.monthly_kwh is None:
            raise ValueError(
                "You chose to enter your monthly units, but no number was given."
            )
        if method == "equipment" and not self.equipment and not self.pumps:
            raise ValueError(
                "You chose to work consumption out from your equipment, but nothing was "
                "listed. Add at least one item."
            )
        if method == "floor_area" and self.floor_area_m2 is None:
            raise ValueError(
                "You chose to estimate from building size, but no floor area was given."
            )
        return self

    @model_validator(mode="after")
    def _existing_system_is_described(self) -> EstimateRequest:
        if self.goal == "existing" and not self.system.panel_count:
            raise ValueError(
                "Tell us how many panels you already have, so we can work out what your "
                "system produces."
            )
        return self

    @model_validator(mode="after")
    def _battery_sane(self) -> EstimateRequest:
        b = self.battery
        if not b.wanted and (b.capacity_kwh or b.desired_backup_hours):
            # Not an error: the user changed their mind and the details are stale. Honour
            # the intent rather than rejecting a request over a leftover field.
            pass
        return self


class EstimateUpdateRequest(BaseModel):
    """Re-run a saved estimate with edited assumptions (§28)."""

    model_config = ConfigDict(extra="forbid")

    system: SystemSpec | None = None
    money: MoneySpec | None = None
    battery: BatterySpec | None = None
    operations: OperationsSpec | None = None
    label: str | None = Field(default=None, max_length=120)


class RenameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=120)


class ScenarioSpec(BaseModel):
    """One option in a side-by-side comparison (§27)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=80)
    capacity_kwp: float | None = Field(default=None, gt=0, le=1_000_000)
    battery_kwh: float | None = Field(default=None, ge=0, le=100_000)


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base: EstimateRequest
    scenarios: list[ScenarioSpec] = Field(min_length=2, max_length=5)

    @field_validator("scenarios")
    @classmethod
    def _distinct(cls, v: list[ScenarioSpec]) -> list[ScenarioSpec]:
        names = [s.name.strip().lower() for s in v]
        if len(set(names)) != len(names):
            raise ValueError("Give each option a different name so the comparison is readable.")
        if all(s.capacity_kwp is None for s in v):
            raise ValueError(
                "At least one option needs a system size, otherwise every option is identical."
            )
        return v
