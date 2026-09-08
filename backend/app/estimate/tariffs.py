"""Electricity tariffs and currency.

Converting a monthly bill into kilowatt-hours is the single most load-bearing assumption
in the whole consumer flow: for a user who chose "I know my electricity bill", it sets the
consumption figure, which sets the recommended system size, which sets every downstream
number. So it is done explicitly, with the tariff visible and editable, rather than by
folding a hidden divisor into a formula.

Two things this module refuses to do:

- **Present a default tariff as your tariff.** The defaults here are planning figures.
  The user is told which one was applied and asked to correct it from their bill.
- **Ignore subsidised agricultural supply.** In much of India farm connections are billed
  far below cost or on a flat per-horsepower basis, and in several states pump supply is
  effectively free. A solar estimate that quietly bills a farmer's displaced units at a
  commercial rate would overstate their savings several times over. That case is detected
  and reported rather than averaged away.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

UserType = Literal[
    "home",
    "farm",
    "shop",
    "commercial",
    "institution",
    "exploring",
]


@dataclass(frozen=True)
class Currency:
    code: str
    symbol: str
    name: str
    # Where the symbol sits relative to the figure. Localisation (§33) needs this rather
    # than a hardcoded f"{symbol}{value}" scattered through the frontend.
    symbol_position: Literal["prefix", "suffix"] = "prefix"

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "symbol": self.symbol,
            "name": self.name,
            "symbol_position": self.symbol_position,
        }


_EURO = Currency("EUR", "€", "Euro")

CURRENCIES: dict[str, Currency] = {
    "IN": Currency("INR", "₹", "Indian rupee"),
    "US": Currency("USD", "$", "US dollar"),
    "GB": Currency("GBP", "£", "Pound sterling"),
    "AU": Currency("AUD", "A$", "Australian dollar"),
    "CA": Currency("CAD", "C$", "Canadian dollar"),
    "ZA": Currency("ZAR", "R", "South African rand"),
    "BR": Currency("BRL", "R$", "Brazilian real"),
    "KE": Currency("KES", "KSh", "Kenyan shilling"),
    "NG": Currency("NGN", "₦", "Nigerian naira"),
    "PK": Currency("PKR", "₨", "Pakistani rupee"),
    "BD": Currency("BDT", "৳", "Bangladeshi taka"),
    "LK": Currency("LKR", "Rs", "Sri Lankan rupee"),
    "NP": Currency("NPR", "Rs", "Nepalese rupee"),
    "ID": Currency("IDR", "Rp", "Indonesian rupiah"),
    "PH": Currency("PHP", "₱", "Philippine peso"),
    "JP": Currency("JPY", "¥", "Japanese yen"),
    "CN": Currency("CNY", "¥", "Chinese yuan"),
    "MX": Currency("MXN", "$", "Mexican peso"),
    "AE": Currency("AED", "AED", "UAE dirham"),
    "SA": Currency("SAR", "SR", "Saudi riyal"),
    "CH": Currency("CHF", "CHF", "Swiss franc"),
    "SE": Currency("SEK", "kr", "Swedish krona", "suffix"),
    "NO": Currency("NOK", "kr", "Norwegian krone", "suffix"),
    "DK": Currency("DKK", "kr", "Danish krone", "suffix"),
    "PL": Currency("PLN", "zł", "Polish złoty", "suffix"),
    # The eurozone. Sharing one instance keeps them impossible to get subtly out of step.
    **dict.fromkeys(("DE", "ES", "FR", "IT", "PT", "NL", "BE", "AT", "IE", "GR", "FI", "SK", "SI", "LT", "LV", "EE", "LU", "CY", "MT", "HR"), _EURO),
}

DEFAULT_CURRENCY = Currency("USD", "$", "US dollar")

# Approximate units of each currency per US dollar.
#
# These exist so that a figure and its currency symbol always agree in scale. Serving a
# Kenyan user "KSh 0.15 per unit" because the generic default happens to be denominated in
# dollars is not an approximation — it is off by a factor of a hundred and thirty, and it
# looks authoritative while being nonsense.
#
# Rates move, and these are not updated live. They are used only to place a *default* in
# the right order of magnitude, never to convert a figure the user supplied, and every
# figure derived from one is labelled an editable planning value.
_UNITS_PER_USD: dict[str, float] = {
    "USD": 1.0, "INR": 83.0, "EUR": 0.92, "GBP": 0.79, "AUD": 1.52,
    "CAD": 1.36, "ZAR": 18.2, "BRL": 5.2, "KES": 130.0, "NGN": 1500.0,
    "PKR": 278.0, "BDT": 118.0, "LKR": 300.0, "NPR": 133.0, "IDR": 16000.0,
    "PHP": 57.0, "JPY": 150.0, "CNY": 7.2, "MXN": 18.5, "AED": 3.67,
    "SAR": 3.75, "CHF": 0.88, "SEK": 10.6, "NOK": 10.8, "DKK": 6.9,
    "PLN": 4.0,
}


def units_per_usd(currency_code: str) -> float | None:
    """How many units of this currency make a dollar, or None if we do not know."""
    return _UNITS_PER_USD.get((currency_code or "").upper())


def currency_for_country(country_code: str | None) -> Currency:
    """The currency to present figures in.

    A currency is only offered when its scale is known. Otherwise the dollar is used —
    an unfamiliar currency is a smaller problem than a familiar one carrying a number that
    is wrong by two orders of magnitude.
    """
    if not country_code:
        return DEFAULT_CURRENCY
    currency = CURRENCIES.get(country_code.upper())
    if currency is None or units_per_usd(currency.code) is None:
        return DEFAULT_CURRENCY
    return currency


@dataclass(frozen=True)
class TariffDefault:
    """A representative retail electricity rate for planning."""

    rate_per_kwh: float
    fixed_monthly_charge: float
    export_rate_per_kwh: float | None
    note: str
    subsidised: bool = False


# Representative retail rates in local currency per kWh. These are planning defaults,
# deliberately mid-range rather than optimistic, and every result that uses one says so.
_TARIFFS: dict[str, dict[str, TariffDefault]] = {
    "IN": {
        "home": TariffDefault(
            7.5, 100.0, 3.0,
            "Domestic supply is slab-priced, so a larger bill usually means a higher rate "
            "on the top slab than this flat average.",
        ),
        "farm": TariffDefault(
            2.5, 0.0, 2.5,
            "Agricultural supply is subsidised in most Indian states, and in several it is "
            "free for pump connections. If you pay little or nothing for pump power, your "
            "savings come from reliability and daytime availability rather than from the "
            "bill — tell us your actual rate so we do not overstate them.",
            subsidised=True,
        ),
        "shop": TariffDefault(
            9.0, 250.0, 3.5,
            "Small commercial supply typically costs more per unit than domestic supply.",
        ),
        "commercial": TariffDefault(
            9.5, 1_500.0, 3.5,
            "Commercial and industrial supply usually carries a demand charge on top of "
            "the per-unit rate, which this flat figure does not represent.",
        ),
        "institution": TariffDefault(
            8.0, 500.0, 3.0,
            "Institutional supply is often billed on a commercial schedule.",
        ),
        "exploring": TariffDefault(7.5, 100.0, 3.0, "Domestic supply, as a starting point."),
    },
    "US": {
        "home": TariffDefault(0.16, 12.0, 0.08, "US residential average; varies widely by state."),
        "farm": TariffDefault(0.13, 20.0, 0.07, "Agricultural supply; varies widely by utility."),
        "shop": TariffDefault(0.14, 30.0, 0.07, "Small commercial average."),
        "commercial": TariffDefault(0.13, 150.0, 0.06,
                                    "Commercial supply usually adds a demand charge."),
        "institution": TariffDefault(0.13, 80.0, 0.06, "Institutional supply."),
        "exploring": TariffDefault(0.16, 12.0, 0.08, "Residential supply, as a starting point."),
    },
}

_FALLBACK_TARIFF = TariffDefault(
    0.15, 10.0, 0.07,
    "A generic planning rate, because we do not hold a regional default for your country. "
    "Replace it with the rate from your bill.",
)


def default_tariff(country_code: str | None, user_type: str) -> TariffDefault:
    """Representative tariff for a country and user type.

    Where a regional table exists its rates are already denominated in the local currency.
    Where one does not, the generic rate — which is expressed in dollars — is converted, so
    the number and the symbol beside it are never in different scales.
    """
    table = _TARIFFS.get((country_code or "").upper())
    if table is not None:
        return table.get(user_type) or table.get("home") or _FALLBACK_TARIFF

    currency = currency_for_country(country_code)
    rate = units_per_usd(currency.code) or 1.0
    if rate == 1.0:
        return _FALLBACK_TARIFF
    return TariffDefault(
        rate_per_kwh=round(_FALLBACK_TARIFF.rate_per_kwh * rate, 2),
        fixed_monthly_charge=round(_FALLBACK_TARIFF.fixed_monthly_charge * rate, 2),
        export_rate_per_kwh=round((_FALLBACK_TARIFF.export_rate_per_kwh or 0.0) * rate, 2),
        note=_FALLBACK_TARIFF.note,
    )


def consumption_from_bill(
    *,
    monthly_bill: float,
    rate_per_kwh: float,
    fixed_monthly_charge: float = 0.0,
) -> tuple[float, list[str]]:
    """Convert a monthly bill into monthly kWh.

    Returns the estimate and any notes worth surfacing. The fixed charge is removed first:
    it buys no energy, and treating the whole bill as energy inflates consumption — which
    would then inflate the recommended system size and the claimed savings together.
    """
    notes: list[str] = []
    if rate_per_kwh <= 0:
        raise ValueError("The electricity rate must be greater than zero.")

    energy_portion = monthly_bill - max(0.0, fixed_monthly_charge)
    if energy_portion <= 0:
        notes.append(
            "The bill you entered is at or below the fixed monthly service charge, so it "
            "implies almost no metered consumption. Check the amount, or enter your units "
            "directly instead."
        )
        return 0.0, notes

    kwh = energy_portion / rate_per_kwh
    notes.append(
        f"Estimated from your bill after removing the fixed service charge, at a rate of "
        f"{rate_per_kwh:g} per unit. If your bill shows the units used, entering that "
        f"directly is more accurate."
    )
    return kwh, notes
