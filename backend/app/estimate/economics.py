"""Cost, savings, payback and emissions — with every input on the table.

§20 and §25 both insist financial output must state its assumptions and must not be
fabricated. The line this module walks: showing no financial figure at all would fail the
user, who genuinely needs to know whether this is worth doing, while showing a confident
₹-figure built on a guessed tariff and a guessed installed cost would be worse than
useless. So every figure here is computed from named, editable inputs and travels with
them. Change the tariff and every number moves.

What is modelled: degradation of the array year by year, escalation of the electricity
price, self-consumed units valued at the retail rate and exported units at the export rate,
and ongoing maintenance. What is deliberately not modelled: financing and interest,
inflation beyond the tariff, subsidies and rebates (they vary by scheme and expire), tax
treatment, and demand charges on commercial connections. Each of those is stated rather
than silently assumed away.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.estimate import assumptions as A
from app.estimate.balance import EnergyBalance


@dataclass
class Economics:
    currency_code: str
    currency_symbol: str
    system_cost: float
    battery_cost: float
    total_capex: float
    annual_savings_year1: float
    annual_import_savings: float
    annual_export_income: float
    lifetime_savings: float
    lifetime_years: int
    payback_years: float | None
    roi_pct: float | None
    lcoe_per_kwh: float | None
    annual_om_cost: float
    co2_avoided_kg_per_year: float
    co2_avoided_tonnes_lifetime: float
    yearly: list[dict[str, float]] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "currency_code": self.currency_code,
            "currency_symbol": self.currency_symbol,
            "system_cost": round(self.system_cost, 0),
            "battery_cost": round(self.battery_cost, 0),
            "total_capex": round(self.total_capex, 0),
            "annual_savings_year1": round(self.annual_savings_year1, 0),
            "annual_import_savings": round(self.annual_import_savings, 0),
            "annual_export_income": round(self.annual_export_income, 0),
            "monthly_savings_year1": round(self.annual_savings_year1 / 12.0, 0),
            "lifetime_savings": round(self.lifetime_savings, 0),
            "lifetime_years": self.lifetime_years,
            "payback_years": round(self.payback_years, 1) if self.payback_years else None,
            "roi_pct": round(self.roi_pct, 1) if self.roi_pct is not None else None,
            "lcoe_per_kwh": round(self.lcoe_per_kwh, 2) if self.lcoe_per_kwh else None,
            "annual_om_cost": round(self.annual_om_cost, 0),
            "co2_avoided_kg_per_year": round(self.co2_avoided_kg_per_year, 0),
            "co2_avoided_tonnes_per_year": round(self.co2_avoided_kg_per_year / 1000.0, 2),
            "co2_avoided_tonnes_lifetime": round(self.co2_avoided_tonnes_lifetime, 1),
            "yearly": self.yearly,
            "caveats": self.caveats,
        }


def compute(
    *,
    balance: EnergyBalance,
    capacity_kwp: float,
    currency_code: str,
    currency_symbol: str,
    import_rate_per_kwh: float,
    export_rate_per_kwh: float | None,
    country_code: str | None,
    battery_kwh: float = 0.0,
    system_cost_override: float | None = None,
    battery_cost_override: float | None = None,
    lifetime_years: int = A.DEFAULT_SYSTEM_LIFETIME_YEARS,
    degradation_rate: float = A.DEFAULT_DEGRADATION_RATE_PER_YEAR,
    tariff_escalation: float = A.DEFAULT_TARIFF_ESCALATION_PER_YEAR,
    om_fraction: float = A.DEFAULT_ANNUAL_OM_FRACTION_OF_CAPEX,
    tariff_is_subsidised: bool = False,
) -> Economics:
    """Project the finances over the system's life."""
    caveats: list[str] = []

    system_cost = (
        float(system_cost_override)
        if system_cost_override is not None
        else capacity_kwp * A.indicative_cost_per_kwp(capacity_kwp, currency_code)
    )
    if battery_cost_override is not None:
        battery_cost = float(battery_cost_override)
    elif battery_kwh:
        battery_cost = float(battery_kwh) * A.battery_cost_per_kwh(currency_code)
    else:
        battery_cost = 0.0

    total_capex = system_cost + battery_cost
    annual_om = total_capex * om_fraction

    export_rate = export_rate_per_kwh if export_rate_per_kwh is not None else 0.0

    year1_import_savings = balance.self_consumed_kwh * import_rate_per_kwh
    year1_export_income = balance.exported_kwh * export_rate
    year1_savings = year1_import_savings + year1_export_income

    # ------------------------------------------------------------------ year by year
    yearly: list[dict[str, float]] = []
    cumulative = -total_capex
    payback_years: float | None = None
    lifetime_savings = 0.0
    lifetime_generation = 0.0

    for year in range(1, int(lifetime_years) + 1):
        performance = (1.0 - degradation_rate) ** (year - 1)
        escalation = (1.0 + tariff_escalation) ** (year - 1)

        generation = balance.generation_kwh * performance
        savings = (
            balance.self_consumed_kwh * performance * import_rate_per_kwh
            + balance.exported_kwh * performance * export_rate
        ) * escalation
        net = savings - annual_om

        previous_cumulative = cumulative
        cumulative += net
        lifetime_savings += savings
        lifetime_generation += generation

        if payback_years is None and cumulative >= 0 and net > 0:
            # Interpolate within the year rather than reporting a whole-year step.
            fraction = -previous_cumulative / net if net else 0.0
            payback_years = (year - 1) + min(max(fraction, 0.0), 1.0)

        yearly.append(
            {
                "year": year,
                "generation_kwh": round(generation, 0),
                "savings": round(savings, 0),
                "net_cash_flow": round(net, 0),
                "cumulative_cash_flow": round(cumulative, 0),
            }
        )

    net_lifetime = lifetime_savings - (annual_om * lifetime_years)
    roi_pct = ((net_lifetime - total_capex) / total_capex * 100.0) if total_capex > 0 else None
    lcoe = (
        (total_capex + annual_om * lifetime_years) / lifetime_generation
        if lifetime_generation > 0
        else None
    )

    # ------------------------------------------------------------------- emissions
    factor = A.grid_emission_factor(country_code)
    co2_per_year = balance.generation_kwh * factor
    # Lifetime emissions follow the degrading output, not a flat multiplication.
    co2_lifetime_kg = sum(
        balance.generation_kwh * ((1.0 - degradation_rate) ** (y - 1)) * factor
        for y in range(1, int(lifetime_years) + 1)
    )

    # --------------------------------------------------------------------- caveats
    if payback_years is None:
        caveats.append(
            "At these rates the system does not pay for itself within its modelled life. "
            "That usually means the electricity it displaces is very cheap, or the assumed "
            "installed cost is too high — check both before drawing a conclusion."
        )
    if tariff_is_subsidised:
        caveats.append(
            "Your supply appears to be subsidised, so each unit of solar displaces a "
            "cheap unit and the money saved is small. The real benefit in this case is "
            "usually reliable daytime power rather than a lower bill."
        )
    if export_rate_per_kwh is None:
        caveats.append(
            "No export rate was set, so exported electricity is valued at zero. If your "
            "utility pays for export, enter the rate to see the difference."
        )
    elif export_rate < import_rate_per_kwh * 0.6 and balance.exported_kwh > 0:
        caveats.append(
            f"Exported units earn much less than the units you buy, so using power during "
            f"the day is worth far more than exporting it. About "
            f"{balance.exported_kwh:,.0f} kWh a year is currently exported."
        )
    caveats.append(
        "Financing costs, subsidies and tax treatment are not included. Subsidy schemes in "
        "particular change often, and a current one could shorten the payback considerably."
    )
    if system_cost_override is None:
        caveats.append(
            "The installed cost is a typical market figure, not a quotation. Replace it "
            "with a real quote for a payback figure you can rely on."
        )

    return Economics(
        currency_code=currency_code,
        currency_symbol=currency_symbol,
        system_cost=system_cost,
        battery_cost=battery_cost,
        total_capex=total_capex,
        annual_savings_year1=year1_savings,
        annual_import_savings=year1_import_savings,
        annual_export_income=year1_export_income,
        lifetime_savings=lifetime_savings,
        lifetime_years=int(lifetime_years),
        payback_years=payback_years,
        roi_pct=roi_pct,
        lcoe_per_kwh=lcoe,
        annual_om_cost=annual_om,
        co2_avoided_kg_per_year=co2_per_year,
        co2_avoided_tonnes_lifetime=co2_lifetime_kg / 1000.0,
        yearly=yearly,
        caveats=caveats,
    )


def equivalence(co2_kg_per_year: float) -> list[dict[str, Any]]:
    """Plain-language comparisons for an emissions figure.

    Kilograms of CO₂ mean little to most people. These are rounded, deliberately coarse
    equivalences — presented as "roughly the same as", never as a precise claim.
    """
    return [
        {
            "key": "trees",
            # A mature tree absorbs on the order of 20 kg CO2 a year; species, age and
            # climate move this a great deal, so it is offered as an order of magnitude.
            "value": round(co2_kg_per_year / 20.0),
            "unit": "trees",
            "phrase": "roughly what this many mature trees absorb in a year",
        },
        {
            "key": "car_km",
            # Around 0.12 kg CO2 per km for a typical petrol car.
            "value": round(co2_kg_per_year / 0.12 / 100) * 100,
            "unit": "km",
            "phrase": "about as much as driving a petrol car this far",
        },
    ]
