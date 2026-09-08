"""Where the energy actually goes: used on site, exported, or drawn from the grid.

Annual generation against annual consumption is the number most solar calculators stop at,
and it quietly misleads. Solar arrives in the middle of the day. A household that uses most
of its electricity after dark can generate 100 % of its annual consumption and still buy
most of its evening electricity from the grid, exporting the surplus at a fraction of what
it pays to import.

So the balance is computed hour by hour against the load shape, never as a ratio of annual
totals. That distinction changes the savings figure materially, and it is the whole reason
storage is worth anything.

Battery modelling (§26) is a straightforward greedy dispatch: store surplus, discharge into
deficit, respect the power limit, the usable depth of discharge and the round-trip losses.
It does not model tariff arbitrage, degradation of the cells over time, or grid export
limits, and it says so rather than implying a sophistication it does not have.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from app.estimate.demand import DemandEstimate, hourly_profile

# Lithium iron phosphate is the common domestic and small-commercial chemistry now, and
# these are its representative characteristics. Editable, like every other default.
DEFAULT_ROUND_TRIP_EFFICIENCY = 0.90
DEFAULT_USABLE_FRACTION = 0.90       # depth of discharge
DEFAULT_C_RATE = 0.5                 # charge/discharge power as a fraction of capacity


@dataclass
class EnergyBalance:
    """Annual split of generation and consumption."""

    generation_kwh: float
    consumption_kwh: float
    self_consumed_kwh: float
    exported_kwh: float
    imported_kwh: float
    solar_offset_fraction: float       # share of consumption met by solar
    self_consumption_fraction: float   # share of generation used on site
    grid_dependence_fraction: float    # share of consumption still bought
    battery: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generation_kwh": round(self.generation_kwh, 0),
            "consumption_kwh": round(self.consumption_kwh, 0),
            "self_consumed_kwh": round(self.self_consumed_kwh, 0),
            "exported_kwh": round(self.exported_kwh, 0),
            "imported_kwh": round(self.imported_kwh, 0),
            "solar_offset_fraction": round(self.solar_offset_fraction, 4),
            "solar_offset_pct": round(self.solar_offset_fraction * 100, 1),
            "self_consumption_fraction": round(self.self_consumption_fraction, 4),
            "self_consumption_pct": round(self.self_consumption_fraction * 100, 1),
            "grid_dependence_fraction": round(self.grid_dependence_fraction, 4),
            "grid_dependence_pct": round(self.grid_dependence_fraction * 100, 1),
            "battery": self.battery,
            "notes": self.notes,
        }


def _aligned_load(generation: pd.Series, demand: DemandEstimate) -> np.ndarray:
    """Hourly load aligned to the generation series, by local hour of day."""
    profile = hourly_profile(demand.profile_key)
    hours = generation.index.hour
    return profile[hours] * demand.daily_kwh


def energy_balance(
    generation: pd.Series,
    demand: DemandEstimate,
    *,
    battery_kwh: float | None = None,
    round_trip_efficiency: float = DEFAULT_ROUND_TRIP_EFFICIENCY,
    usable_fraction: float = DEFAULT_USABLE_FRACTION,
    c_rate: float = DEFAULT_C_RATE,
    export_allowed: bool = True,
) -> EnergyBalance:
    """Split generation and consumption hour by hour over the modelled period.

    ``generation`` is the hourly AC series from the climatology, indexed in local time and
    typically covering several years. Totals are divided back to a per-year figure so the
    result reads as a typical year.
    """
    if generation.empty:
        raise ValueError("Cannot compute an energy balance without a generation series.")

    gen = generation.to_numpy(dtype=np.float64)
    load = _aligned_load(generation, demand)
    years = max(len(gen) / (365.25 * 24.0), 1e-9)
    notes: list[str] = []

    surplus = gen - load
    direct_self = np.minimum(gen, load)

    battery_payload: dict[str, Any] | None = None
    battery_discharged = 0.0
    battery_charged = 0.0

    if battery_kwh and battery_kwh > 0:
        usable = battery_kwh * usable_fraction
        power_limit = battery_kwh * c_rate
        eta = float(np.sqrt(round_trip_efficiency))

        soc = 0.0            # energy held in the battery, kWh
        charged_total = 0.0  # drawn from surplus generation
        discharged_total = 0.0  # delivered to load

        for s in surplus:
            if s > 0:
                headroom = (usable - soc) / eta if eta > 0 else 0.0
                take = min(s, power_limit, max(0.0, headroom))
                soc += take * eta
                charged_total += take
            elif s < 0:
                give = min(-s, power_limit, soc * eta)
                soc -= give / eta if eta > 0 else 0.0
                discharged_total += give

        battery_discharged = float(discharged_total)
        battery_charged = float(charged_total)
        cycles = charged_total / usable / years if usable > 0 else 0.0

        battery_payload = {
            "capacity_kwh": round(battery_kwh, 2),
            "usable_capacity_kwh": round(usable, 2),
            "usable_fraction": usable_fraction,
            "round_trip_efficiency": round_trip_efficiency,
            "max_power_kw": round(power_limit, 2),
            "annual_charged_kwh": round(charged_total / years, 0),
            "annual_discharged_kwh": round(discharged_total / years, 0),
            "annual_round_trip_loss_kwh": round((charged_total - discharged_total) / years, 0),
            "equivalent_full_cycles_per_year": round(cycles, 0),
            "note": (
                "Modelled as storing surplus during the day and releasing it when demand "
                "exceeds generation. It does not model buying cheap grid power to resell, "
                "cell ageing, or any export limit your utility may impose."
            ),
        }
        notes.append(
            f"A {battery_kwh:g} kWh battery moves about "
            f"{discharged_total / years:,.0f} kWh a year from daytime to evening, after "
            f"round-trip losses of {(charged_total - discharged_total) / years:,.0f} kWh."
        )

    # Two ledgers that must each balance:
    #   generation  = used directly + stored + exported
    #   consumption = used directly + released from storage + imported
    # Round-trip losses are the gap between what was stored and what came back out, and
    # they belong to neither side — which is precisely why storage is not free.
    total_gen = float(gen.sum())
    total_load = float(load.sum())
    direct = float(direct_self.sum())

    self_consumed = direct + battery_discharged
    exported = max(0.0, total_gen - direct - battery_charged)
    imported = max(0.0, total_load - self_consumed)

    if not export_allowed and exported > 0:
        notes.append(
            f"Your setup does not export to the grid, so about {exported / years:,.0f} kWh "
            f"a year of surplus generation would simply go unused. A battery, or shifting "
            f"some use into daylight hours, would capture part of it."
        )

    return EnergyBalance(
        generation_kwh=total_gen / years,
        consumption_kwh=total_load / years,
        self_consumed_kwh=self_consumed / years,
        exported_kwh=exported / years,
        imported_kwh=imported / years,
        solar_offset_fraction=(self_consumed / total_load) if total_load > 0 else 0.0,
        self_consumption_fraction=(self_consumed / total_gen) if total_gen > 0 else 0.0,
        grid_dependence_fraction=(imported / total_load) if total_load > 0 else 0.0,
        battery=battery_payload,
        notes=notes,
    )


@dataclass
class BatteryRecommendation:
    capacity_kwh: float
    usable_kwh: float
    basis: str
    backup_hours: float | None
    critical_load_kw: float | None
    charging_note: str
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "capacity_kwh": round(self.capacity_kwh, 1),
            "usable_kwh": round(self.usable_kwh, 1),
            "basis": self.basis,
            "backup_hours": round(self.backup_hours, 1) if self.backup_hours else None,
            "critical_load_kw": round(self.critical_load_kw, 2) if self.critical_load_kw else None,
            "charging_note": self.charging_note,
            "notes": self.notes,
        }


def recommend_battery(
    *,
    demand: DemandEstimate,
    generation: pd.Series | None = None,
    desired_backup_hours: float | None = None,
    critical_load_kw: float | None = None,
    stated_capacity_kwh: float | None = None,
    usable_fraction: float = DEFAULT_USABLE_FRACTION,
    grid_connected: bool = True,
) -> BatteryRecommendation:
    """Size storage from what the user said they need (§26).

    Two different needs produce two different batteries, and conflating them is how people
    end up disappointed: *backup through an outage* is sized from the critical load and how
    long it must last, while *using more of your own solar* is sized from the evening
    shortfall. Whichever the user described is the one used, and the other is mentioned.
    """
    notes: list[str] = []

    if stated_capacity_kwh and stated_capacity_kwh > 0:
        usable = stated_capacity_kwh * usable_fraction
        backup = (usable / critical_load_kw) if critical_load_kw else None
        return BatteryRecommendation(
            capacity_kwh=stated_capacity_kwh,
            usable_kwh=usable,
            basis="The battery size you specified.",
            backup_hours=backup,
            critical_load_kw=critical_load_kw,
            charging_note=_charging_note(stated_capacity_kwh, generation),
            notes=notes,
        )

    if desired_backup_hours and desired_backup_hours > 0:
        load_kw = critical_load_kw
        if not load_kw:
            # Fall back to the average draw rather than the peak: sizing a backup battery
            # on the peak hour would oversize it for most of an outage.
            load_kw = demand.daily_kwh / 24.0
            notes.append(
                "You did not tell us which loads must stay on, so we sized the battery on "
                "your average draw. Listing just the essentials — lights, fans, a fridge — "
                "usually gives a smaller and cheaper battery."
            )
        usable_needed = load_kw * desired_backup_hours
        capacity = usable_needed / usable_fraction
        return BatteryRecommendation(
            capacity_kwh=capacity,
            usable_kwh=usable_needed,
            basis=(
                f"Sized to run {load_kw:.2f} kW of essential load for "
                f"{desired_backup_hours:g} hours."
            ),
            backup_hours=desired_backup_hours,
            critical_load_kw=load_kw,
            charging_note=_charging_note(capacity, generation),
            notes=notes,
        )

    # No stated backup requirement: size to soak up the evening shortfall.
    profile = hourly_profile(demand.profile_key)
    evening = float(profile[18:24].sum() + profile[0:6].sum()) * demand.daily_kwh
    capacity = evening / usable_fraction
    notes.append(
        "Sized to cover the electricity you typically use after dark, so that more of your "
        "own solar is used at home instead of being exported."
    )
    if not grid_connected:
        capacity *= 1.5
        notes.append(
            "Because you have no grid connection, the battery has been sized larger to "
            "carry you through a cloudy day. Off-grid systems need real margin — a run of "
            "overcast days is the case that leaves people in the dark."
        )
    return BatteryRecommendation(
        capacity_kwh=capacity,
        usable_kwh=capacity * usable_fraction,
        basis="Sized to store your evening and overnight consumption.",
        backup_hours=None,
        critical_load_kw=None,
        charging_note=_charging_note(capacity, generation),
        notes=notes,
    )


def _charging_note(capacity_kwh: float, generation: pd.Series | None) -> str:
    """Whether the array can realistically fill this battery."""
    if generation is None or generation.empty:
        return (
            "Check that your array generates enough surplus during the day to fill this "
            "battery."
        )
    years = max(len(generation) / (365.25 * 24.0), 1e-9)
    daily_gen = float(generation.sum()) / years / 365.25
    if daily_gen <= 0:
        return "The array generates nothing, so this battery could not be charged from solar."
    share = capacity_kwh / daily_gen
    if share > 0.8:
        return (
            f"This battery holds about {share:.0%} of a typical day's generation "
            f"({daily_gen:,.1f} kWh). On cloudy days it will not fill from solar alone."
        )
    return (
        f"A typical day generates about {daily_gen:,.1f} kWh, comfortably enough to charge "
        f"this battery alongside your daytime use."
    )
