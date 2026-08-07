#!/usr/bin/env python3
"""Does a host make money serving inference on consumer hardware?

This is the "one spreadsheet" ROADMAP Stage D2 asked for, written as a script so it
can be re-run when prices move instead of aging into another false claim in prose.
`docs/decisions/D2-economics.md` states the conclusion; this file is where it comes
from, and `tests/test_economics.py` fails if the conclusion changes.

Run it:

    .venv/bin/python scripts/economics.py
    .venv/bin/python scripts/economics.py --electricity-usd-per-kwh 0.09

Every input is an assumption and every assumption is named. Where a number is
uncertain the value chosen is the one most FAVOURABLE to the host, so that a
negative result is not an artefact of pessimistic inputs.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, replace

# --- Assumptions -----------------------------------------------------------
# Sources are commodity market observations as of 2026-08 rather than a citable
# dataset, which is itself a reason to treat the output as an order of magnitude
# and not a forecast. See "Honesty about these numbers" at the bottom of the file.

SECONDS_PER_HOUR = 3600
TOKENS_PER_MILLION = 1_000_000


@dataclass(frozen=True)
class Assumptions:
    """Inputs to the model. All of these are arguable; none of them are hidden."""

    # Hardware. An RTX 4090-class consumer card, which is the most capable thing a
    # residential host plausibly owns.
    gpu_price_usd: float = 1800.0
    gpu_life_years: float = 3.0
    gpu_load_watts: float = 450.0
    # The rest of the machine, under inference load.
    system_load_watts: float = 100.0
    # What the machine draws to be *available* while serving nothing. This is the
    # number that decides the answer and the one most often left out.
    idle_watts: float = 75.0

    # Throughput, 8B-class model at 4-bit quantisation.
    # Single stream is what a home node actually sees: requests arrive one at a time.
    tokens_per_second_single_stream: float = 110.0
    # What the same card does when continuously batched, i.e. datacentre conditions.
    tokens_per_second_batched: float = 1100.0

    # Fraction of wall-clock time the node is actually generating tokens. A host
    # with real request volume might reach 10%; most reach far less.
    utilisation: float = 0.10

    electricity_usd_per_kwh: float = 0.17

    # Blended commodity price for an 8B-class model per 1M tokens, 2026-08.
    # Chosen at the HIGH end of what is publicly advertised, again to favour the host.
    commodity_api_usd_per_1m_tokens: float = 0.15


@dataclass(frozen=True)
class Scenario:
    name: str
    usd_per_1m_tokens: float
    note: str

    def margin_vs(self, commodity: float) -> float:
        """Positive means the host makes money at commodity pricing."""
        return commodity - self.usd_per_1m_tokens


def _energy_cost_per_1m(watts: float, tokens_per_second: float, usd_per_kwh: float) -> float:
    """Electricity to generate 1M tokens at a sustained rate."""
    hours = TOKENS_PER_MILLION / (tokens_per_second * SECONDS_PER_HOUR)
    return (watts / 1000.0) * hours * usd_per_kwh


def marginal_cost_single_stream(a: Assumptions) -> float:
    """Electricity only, hardware treated as sunk, one request at a time.

    This is the number a host would compute if they reasoned "the card is already
    paid for, so anything above the power bill is profit".
    """
    return _energy_cost_per_1m(
        a.gpu_load_watts + a.system_load_watts,
        a.tokens_per_second_single_stream,
        a.electricity_usd_per_kwh,
    )


def marginal_cost_saturated(a: Assumptions) -> float:
    """Electricity only, continuously batched. The best case that is physically real."""
    return _energy_cost_per_1m(
        a.gpu_load_watts + a.system_load_watts,
        a.tokens_per_second_batched,
        a.electricity_usd_per_kwh,
    )


def fully_loaded_cost(a: Assumptions) -> float:
    """Hardware amortisation + idle draw + inference draw, at real utilisation.

    The honest number: it charges the host for the depreciation they are consuming
    and for the power burned while merely being available.
    """
    tokens_per_year = (
        a.tokens_per_second_single_stream * a.utilisation * SECONDS_PER_HOUR * 24 * 365
    )
    if tokens_per_year <= 0:
        return float("inf")
    millions_per_year = tokens_per_year / TOKENS_PER_MILLION

    amortisation_per_year = a.gpu_price_usd / a.gpu_life_years

    hours_per_year = 24 * 365
    idle_hours = hours_per_year * (1 - a.utilisation)
    idle_cost_per_year = (a.idle_watts / 1000.0) * idle_hours * a.electricity_usd_per_kwh

    load_hours = hours_per_year * a.utilisation
    load_cost_per_year = (
        ((a.gpu_load_watts + a.system_load_watts) / 1000.0) * load_hours * a.electricity_usd_per_kwh
    )

    return (amortisation_per_year + idle_cost_per_year + load_cost_per_year) / millions_per_year


def scenarios(a: Assumptions) -> list[Scenario]:
    return [
        Scenario(
            "Fully loaded (hardware + idle + power, 10% utilisation)",
            fully_loaded_cost(a),
            "the honest number a host should use",
        ),
        Scenario(
            "Marginal, single stream (hardware sunk)",
            marginal_cost_single_stream(a),
            "what a home node actually experiences",
        ),
        Scenario(
            "Marginal, saturated with batching (hardware sunk)",
            marginal_cost_saturated(a),
            "requires datacentre-like continuous load",
        ),
    ]


def breakeven_utilisation(a: Assumptions) -> float | None:
    """Utilisation at which the fully loaded cost meets commodity pricing.

    Returns None when no utilisation reaches it -- i.e. even a permanently saturated
    node cannot amortise the hardware at that price, which is the strongest possible
    form of "the economics do not close".
    """
    lo, hi = 1e-6, 1.0
    if fully_loaded_cost(replace(a, utilisation=hi)) > a.commodity_api_usd_per_1m_tokens:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if fully_loaded_cost(replace(a, utilisation=mid)) > a.commodity_api_usd_per_1m_tokens:
            lo = mid
        else:
            hi = mid
    return hi


def verdict(a: Assumptions) -> str:
    """`marketplace` if a realistic host profits, otherwise `donation-network`."""
    honest = fully_loaded_cost(a)
    return "marketplace" if honest < a.commodity_api_usd_per_1m_tokens else "donation-network"


def _parse_args(argv: list[str] | None = None) -> Assumptions:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    defaults = Assumptions()
    for field, value in vars(defaults).items():
        parser.add_argument(f"--{field.replace('_', '-')}", type=float, default=value)
    ns = parser.parse_args(argv)
    return Assumptions(**vars(ns))


def main(argv: list[str] | None = None) -> int:
    a = _parse_args(argv)

    print("Host economics, per 1M output tokens")
    print("=" * 78)
    print(f"  electricity            ${a.electricity_usd_per_kwh:.3f}/kWh")
    print(f"  GPU                    ${a.gpu_price_usd:,.0f} over {a.gpu_life_years:.0f} years")
    print(
        f"  draw                   {a.gpu_load_watts + a.system_load_watts:.0f} W loaded / {a.idle_watts:.0f} W idle"
    )
    print(
        f"  throughput             {a.tokens_per_second_single_stream:.0f} tok/s single, {a.tokens_per_second_batched:.0f} tok/s batched"
    )
    print(f"  utilisation            {a.utilisation:.0%}")
    print(f"  commodity API price    ${a.commodity_api_usd_per_1m_tokens:.3f}/1M")
    print()

    print(f"  {'Scenario':<58}{'Cost':>10}{'Margin':>12}")
    print(f"  {'-' * 58}{'-' * 10}{'-' * 12}")
    for s in scenarios(a):
        margin = s.margin_vs(a.commodity_api_usd_per_1m_tokens)
        sign = "+" if margin >= 0 else "-"
        print(
            f"  {s.name:<58}${s.usd_per_1m_tokens:>8.3f}{sign + '$' + format(abs(margin), '.3f'):>12}"
        )
    print()
    for s in scenarios(a):
        print(f"  {s.name.split(' (')[0]:<58}{s.note}")
    print()

    be = breakeven_utilisation(a)
    if be is None:
        print("  Break-even utilisation:  UNREACHABLE -- a permanently saturated node")
        print("                           still cannot amortise the hardware at this price.")
    else:
        print(f"  Break-even utilisation:  {be:.1%} of wall-clock time generating tokens")
        if be > 0.5:
            print("                           (a residential host cannot supply this)")
    print()

    v = verdict(a)
    print("=" * 78)
    if v == "marketplace":
        print("VERDICT: marketplace -- a realistic host profits. Payouts are worth building.")
    else:
        print("VERDICT: donation-network -- a realistic host loses money per token.")
        print("         Credits are an accounting unit, not a currency. See")
        print("         docs/decisions/D2-economics.md.")
    return 0


# --- Honesty about these numbers -------------------------------------------
# These are estimates, not measurements. Nobody has metered a real node in this
# fleet, because there is no fleet (see docs/decisions/D6-is-there-a-network.md).
# What makes the conclusion usable anyway is its size: the fully loaded figure loses
# by more than an order of magnitude, and the dominant term is hardware amortisation,
# which is not sensitive to any throughput or power number here. A 2x error in every
# input does not change the answer. A change in what hardware hosts run, or a
# reversal in commodity pricing, would -- so re-run this rather than citing it.

if __name__ == "__main__":
    sys.exit(main())
