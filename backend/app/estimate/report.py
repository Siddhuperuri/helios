"""A report somebody can actually hand to another person (§36).

Audience is the point. This document may end up in front of a customer, a manager, an
investor, an EPC contractor or a technical reviewer, and those readers want different
things — but all of them are badly served by a page of unexplained numbers.

So the structure is: the answer first, then what it rests on, then what could move it, then
where the data came from. A reader who stops after the summary has something true. A
reviewer who reads to the end can check every figure against the assumption that produced
it, and can see plainly what this platform does not know.

Markdown rather than PDF, deliberately: it renders in the browser, prints from there, pastes
into an email, and needs no rendering dependency in the backend.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _money(value: float | None, symbol: str) -> str:
    if value is None:
        return "—"
    return f"{symbol}{value:,.0f}"


def _fmt(value: Any, suffix: str = "", digits: int = 0) -> str:
    if value is None:
        return "—"
    if isinstance(value, (int, float)):
        return f"{value:,.{digits}f}{suffix}"
    return f"{value}{suffix}"


def build(payload: dict[str, Any]) -> str:
    """Render a complete estimate as a shareable Markdown report."""
    location = payload.get("location") or {}
    system = payload.get("system") or {}
    generation = payload.get("generation") or {}
    band = payload.get("uncertainty") or {}
    balance = payload.get("balance") or {}
    money = payload.get("economics") or {}
    emissions = payload.get("emissions") or {}
    demand = payload.get("demand") or {}
    explanation = payload.get("explanation") or {}
    currency = payload.get("currency") or {}
    farm = payload.get("farm") or {}

    symbol = currency.get("symbol", "")
    sizing = system.get("sizing") or {}
    orientation = system.get("orientation") or {}

    lines: list[str] = []
    add = lines.append

    # ------------------------------------------------------------------------ header
    add(f"# Solar feasibility estimate — {location.get('label', 'Unnamed location')}")
    add("")
    add(f"*Prepared {datetime.now(timezone.utc).strftime('%d %B %Y')} · "
        f"Estimate {payload.get('estimate_id', '—')}*")
    add("")

    # ----------------------------------------------------------------------- summary
    add("## Summary")
    add("")
    add(explanation.get("summary", ""))
    add("")
    add("| | |")
    add("|---|---|")
    add(f"| **Recommended system** | {_fmt(system.get('capacity_kwp'), ' kW', 2)} |")
    add(f"| **Expected annual generation** | {_fmt(generation.get('annual_kwh'), ' kWh')} |")
    add(f"| **Expected range** | {_fmt(band.get('lower'), ' kWh')} – "
        f"{_fmt(band.get('upper'), ' kWh')} ({band.get('coverage_label', '')}) |")
    add(f"| **Confidence** | {str(band.get('confidence', '—')).title()} |")
    add(f"| **Average day** | {_fmt(generation.get('daily_average_kwh'), ' kWh', 1)} |")
    add(f"| **Average month** | {_fmt(generation.get('monthly_average_kwh'), ' kWh')} |")
    if balance:
        add(f"| **Share of your electricity covered** | "
            f"{_fmt(balance.get('solar_offset_pct'), '%', 0)} |")
    if money:
        add(f"| **Estimated annual saving** | "
            f"{_money(money.get('annual_savings_year1'), symbol)} |")
        add(f"| **Estimated system cost** | {_money(money.get('total_capex'), symbol)} |")
        add(f"| **Payback** | {_fmt(money.get('payback_years'), ' years', 1)} |")
    if emissions:
        add(f"| **CO₂ avoided** | "
            f"{_fmt(emissions.get('co2_avoided_tonnes_per_year'), ' tonnes/year', 2)} |")
    add("")
    add(f"> {band.get('confidence_reason', '')}")
    add("")

    # -------------------------------------------------------------------- the system
    add("## Recommended system")
    add("")
    add(f"- **Capacity:** {_fmt(system.get('capacity_kwp'), ' kW', 2)}")
    add(f"- **Why this size:** {sizing.get('reason', '—')}")
    add(f"- **Space required:** {_fmt(sizing.get('area_required_m2'), ' m²')} "
        f"({_fmt(sizing.get('area_required_sqft'), ' sq ft')})")
    add(f"- **Mounting:** {system.get('installation_type', '—')}")
    add(f"- **Tilt and direction:** {_fmt(orientation.get('tilt_deg'), '°', 1)} facing "
        f"{orientation.get('azimuth_compass', '—')}")
    if orientation.get("note"):
        add(f"- **How that was chosen:** {orientation['note']}")
    add(f"- **Panel type:** {system.get('panel_technology', '—')}")
    add(f"- **Inverter:** {_fmt(system.get('ac_capacity_kw'), ' kW AC', 2)}, "
        f"{_fmt((system.get('inverter_efficiency') or 0) * 100, '%', 1)} efficient")
    if system.get("battery"):
        battery = system["battery"]
        add(f"- **Battery:** {_fmt(battery.get('capacity_kwh'), ' kWh', 1)} "
            f"({_fmt(battery.get('usable_kwh'), ' kWh usable', 1)}) — {battery.get('basis', '')}")
    add("")

    # ---------------------------------------------------------------- monthly detail
    add("## Month by month")
    add("")
    add("| Month | Expected generation | Likely range | Daily average |")
    add("|---|---:|---:|---:|")
    for row in generation.get("monthly_ranges", []):
        add(
            f"| {row['month_name']} | {row['expected_kwh']:,.0f} kWh | "
            f"{row['lower_kwh']:,.0f} – {row['upper_kwh']:,.0f} kWh | "
            f"{row['daily_average_kwh']:,.1f} kWh |"
        )
    add("")
    add(f"Best month: **{generation.get('best_month_name', '—')}**. "
        f"Weakest month: **{generation.get('worst_month_name', '—')}**.")
    add("")

    # ------------------------------------------------------------------ consumption
    if demand:
        add("## Your electricity use")
        add("")
        add(f"- **Estimated consumption:** {_fmt(demand.get('annual_kwh'), ' kWh/year')} "
            f"({_fmt(demand.get('monthly_kwh'), ' kWh/month')})")
        add(f"- **How we worked that out:** {demand.get('method_label', '—')}")
        add(f"- **Daily pattern assumed:** {demand.get('profile_description', '—')}")
        for note in demand.get("notes", []):
            add(f"- {note}")
        add("")

    if balance:
        add("### Where the energy goes")
        add("")
        add("| | kWh/year | Share |")
        add("|---|---:|---:|")
        add(f"| Generated | {balance.get('generation_kwh', 0):,.0f} | — |")
        add(f"| Used on site | {balance.get('self_consumed_kwh', 0):,.0f} | "
            f"{balance.get('self_consumption_pct', 0):,.0f}% of generation |")
        add(f"| Exported | {balance.get('exported_kwh', 0):,.0f} | — |")
        add(f"| Still bought from the grid | {balance.get('imported_kwh', 0):,.0f} | "
            f"{balance.get('grid_dependence_pct', 0):,.0f}% of your use |")
        add("")
        add("Solar arrives in the middle of the day, so what matters is not only how much "
            "is generated but how much of it lines up with when electricity is actually "
            "used.")
        add("")

    # -------------------------------------------------------------------- economics
    if money:
        add("## Financial estimate")
        add("")
        add(f"- **System cost:** {_money(money.get('system_cost'), symbol)}")
        if money.get("battery_cost"):
            add(f"- **Battery cost:** {_money(money.get('battery_cost'), symbol)}")
        add(f"- **Total:** {_money(money.get('total_capex'), symbol)}")
        add(f"- **Saving in year one:** {_money(money.get('annual_savings_year1'), symbol)} "
            f"({_money(money.get('monthly_savings_year1'), symbol)} a month)")
        add(f"- **Payback:** {_fmt(money.get('payback_years'), ' years', 1)}")
        add(f"- **Return over {money.get('lifetime_years', 25)} years:** "
            f"{_fmt(money.get('roi_pct'), '%', 1)}")
        if money.get("lcoe_per_kwh"):
            add(f"- **Cost per unit generated over the system's life:** "
                f"{_money(money.get('lcoe_per_kwh'), symbol)}/kWh")
        add("")
        add("**These figures depend entirely on the assumptions below.**")
        add("")
        for caveat in money.get("caveats", []):
            add(f"- {caveat}")
        add("")

    # ------------------------------------------------------------------------- farm
    if farm and farm.get("sufficient_inputs"):
        add("## What this runs on the farm")
        add("")
        for note in farm.get("notes", []):
            add(f"- {note}")
        add("")

    # ------------------------------------------------------------------ uncertainty
    add("## How certain is this?")
    add("")
    add(f"**{str(band.get('confidence', '—')).title()} confidence.** "
        f"{band.get('confidence_reason', '')}")
    add("")
    add(f"The expected range of {_fmt(band.get('lower'), ' kWh')} to "
        f"{_fmt(band.get('upper'), ' kWh')} comes from these sources, combined:")
    add("")
    add("| Source of uncertainty | Size | Can it be reduced? |")
    add("|---|---:|---|")
    for factor in band.get("factors", []):
        reducible = factor.get("reducible_by") or "No — this is weather that has not happened yet."
        add(f"| **{factor['label']}** — {factor['explanation']} | "
            f"±{factor['relative_pct']:.1f}% | {reducible} |")
    add("")
    if band.get("improvements"):
        add("**To tighten this estimate:**")
        add("")
        for item in band["improvements"]:
            add(f"- {item}")
        add("")

    # ----------------------------------------------------------------- what affects
    if explanation.get("what_affects_this"):
        add("## What could change the result")
        add("")
        for item in explanation["what_affects_this"]:
            add(f"**{item['title']}.** {item['body']}")
            add("")

    # ------------------------------------------------------------------ methodology
    add("## Methodology")
    add("")
    add("This is not a rule-of-thumb calculation. Hourly weather for the exact location was "
        "run through a published photovoltaic conversion chain, hour by hour, across "
        f"{generation.get('rows_used', 0):,} hours of record:")
    add("")
    add("1. **Solar resource** — measured hourly global horizontal irradiance from "
        "reanalysis, for this location.")
    add("2. **Plane-of-array irradiance** — the beam, sky-diffuse and ground-reflected "
        "components on the tilted panel surface (Erbs decomposition, then HDKR "
        "transposition).")
    add("3. **Cell temperature** — from irradiance, air temperature and wind speed "
        "(Faiman model). Hot panels produce less, and hot still days are worse than hot "
        "windy ones.")
    add("4. **DC conversion** — PVWatts v5, with the panel's temperature coefficient "
        "applied against its rating.")
    add("5. **System losses** — soiling, shading, mismatch, wiring, connections, "
        "first-year settling, nameplate tolerance and downtime, combined multiplicatively.")
    add("6. **Inverter conversion** — efficiency and clipping against the inverter's AC "
        "limit.")
    add("7. **Aggregation** — hourly AC energy summed to months and years, then averaged "
        "across the years in the record to give a typical year.")
    add("8. **Degradation** — applied year by year across the system's life for the "
        "financial projection.")
    add("")
    add(f"Inter-annual variability is measured rather than assumed: "
        f"{generation.get('variability_basis', '')}")
    add("")

    # ----------------------------------------------------------------- assumptions
    add("## Assumptions")
    add("")
    add("Every figure above depends on these. Anything marked *You told us* came from you; "
        "everything else is a default this platform chose and you can change.")
    add("")
    add("| Assumption | Value | Where it came from | Why |")
    add("|---|---|---|---|")
    for item in payload.get("assumptions", []):
        value = item.get("value")
        unit = f" {item['unit']}" if item.get("unit") else ""
        rationale = item.get("rationale") or item.get("source") or ""
        add(f"| {item['label']} | {value}{unit} | {item.get('provenance_label', '—')} | "
            f"{rationale} |")
    add("")

    # ---------------------------------------------------------------- data sources
    add("## Data sources")
    add("")
    for source in payload.get("data_sources", []):
        add(f"**{source['category']} — {source['name']}**")
        add("")
        add(f"{source['detail']}")
        add("")
        add(f"*{source['licence']}*")
        add("")
        if source.get("caveat"):
            add(f"> {source['caveat']}")
            add("")

    # --------------------------------------------------------------------- limits
    add("## What this estimate does not do")
    add("")
    add("- It is **modelled, not measured**. No metered generation from an installed "
        "system was available to check it against.")
    add("- The weather data is a **reanalysis grid product**, not a sensor at this address.")
    add("- It does **not** include financing, subsidies or tax treatment, all of which can "
        "change the financial picture substantially.")
    add("- It is **not a structural, electrical or shading survey**. A site visit remains "
        "necessary before installation.")
    add("- Tariffs and equipment costs are planning defaults unless you replaced them with "
        "your own figures.")
    add("")

    if payload.get("warnings"):
        add("## Notes raised while producing this estimate")
        add("")
        for warning in payload["warnings"]:
            add(f"- {warning}")
        add("")

    add("---")
    add("")
    add(payload.get("attribution", ""))
    add("")

    return "\n".join(lines)
