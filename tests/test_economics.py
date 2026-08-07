"""The D2 economics model must keep saying what D2 says it says.

`docs/decisions/D2-economics.md` decides that v1 is a donation network rather than a
marketplace, and everything downstream of that -- credits being non-redeemable, no
payout code, "contributed" instead of "earned" -- rests on the arithmetic in
`scripts/economics.py`.

These tests pin the **conclusion**, not the numbers. A price update that moves the
figures without changing the answer must not fail; a change that flips the answer
must, because at that point D2 needs revising rather than the test needs relaxing.
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import replace
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_economics():
    """Import scripts/economics.py, which is not an installed package."""
    path = REPO_ROOT / "scripts" / "economics.py"
    spec = importlib.util.spec_from_file_location("economics", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["economics"] = module
    spec.loader.exec_module(module)
    return module


economics = _load_economics()


def test_default_verdict_is_donation_network():
    """The load-bearing claim of D2. If this fails, D2 is wrong, not this test."""
    assert economics.verdict(economics.Assumptions()) == "donation-network"


def test_fully_loaded_cost_loses_to_commodity_pricing_by_an_order_of_magnitude():
    """D2 rests on the loss being large, not marginal.

    A 20% loss would be inside the error bars of these estimates and would not
    support a product decision. A 10x loss does.
    """
    a = economics.Assumptions()
    cost = economics.fully_loaded_cost(a)
    assert cost > 10 * a.commodity_api_usd_per_1m_tokens


def test_hardware_amortisation_is_the_dominant_term():
    """D2 claims amortisation dominates -- which is why throughput estimates don't matter.

    Doubling every power and throughput input must move the fully loaded figure by
    less than half, or the conclusion really is sensitive to numbers nobody measured.
    """
    a = economics.Assumptions()
    base = economics.fully_loaded_cost(a)
    perturbed = economics.fully_loaded_cost(
        replace(
            a,
            gpu_load_watts=a.gpu_load_watts * 2,
            system_load_watts=a.system_load_watts * 2,
            idle_watts=a.idle_watts * 2,
        )
    )
    assert abs(perturbed - base) / base < 0.5


def test_conclusion_survives_the_most_favourable_plausible_inputs():
    """Cheap power, a cheap card, and 3x the utilisation still lose.

    This is the test that stops D2 from being an artefact of pessimistic assumptions.
    """
    generous = replace(
        economics.Assumptions(),
        electricity_usd_per_kwh=0.09,  # low-cost grid
        gpu_price_usd=900.0,  # used card
        gpu_life_years=5.0,
        utilisation=0.30,  # 3x what a home host plausibly sustains
    )
    assert economics.verdict(generous) == "donation-network"


def test_saturated_marginal_cost_is_the_only_scenario_that_wins():
    """D2's table says exactly one row closes, and names why it is unavailable."""
    a = economics.Assumptions()
    winners = [
        s for s in economics.scenarios(a) if s.margin_vs(a.commodity_api_usd_per_1m_tokens) > 0
    ]
    assert [s.name for s in winners] == ["Marginal, saturated with batching (hardware sunk)"]


def test_breakeven_is_unreachable_at_default_assumptions():
    """`None` means no utilisation whatsoever amortises the card at commodity prices."""
    assert economics.breakeven_utilisation(economics.Assumptions()) is None


def test_breakeven_is_computed_when_it_exists():
    """The bisection must actually work, not only ever return None.

    Without this, `breakeven_utilisation` returning None unconditionally would pass
    the test above and prove nothing.
    """
    a = replace(economics.Assumptions(), commodity_api_usd_per_1m_tokens=50.0)
    be = economics.breakeven_utilisation(a)
    assert be is not None
    assert 0 < be < 1
    # At the break-even point the cost meets the price.
    assert economics.fully_loaded_cost(replace(a, utilisation=be)) == pytest.approx(50.0, rel=0.01)


def test_verdict_flips_to_marketplace_when_the_arithmetic_says_so():
    """The verdict function must be capable of both answers.

    A function hardcoded to return "donation-network" would satisfy every other test
    in this file. This is the mutation that check exists to catch.
    """
    a = replace(economics.Assumptions(), commodity_api_usd_per_1m_tokens=100.0)
    assert economics.verdict(a) == "marketplace"


def test_script_runs_and_prints_the_verdict():
    """D2 tells a reader to run the script. It must run."""
    assert economics.main([]) == 0
