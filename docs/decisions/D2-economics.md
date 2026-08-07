# D2 — Do the economics close?

**Date:** 2026-08-07
**Status:** Decided — **the economics do not close.**

## The question, restated

ROADMAP Stage 3 builds credentials, metering, a ledger and payouts. All of that is
machinery for paying hosts. If a host loses money per token against commodity API
pricing, then it is machinery for the wrong product, and the right product — a
donation network — has a different design and a different pitch.

## The model

The arithmetic is in `scripts/economics.py`, not in this file, so it can be re-run
when prices move rather than aging into another false claim in prose:

```bash
.venv/bin/python scripts/economics.py
```

It is covered by `tests/test_economics.py`, which pins the *conclusion* — that the
break-even utilisation exceeds what a residential host can supply — rather than
pinning the numbers, so a price update fails the test only if it changes the answer.

### Result (default assumptions, 2026-08)

| Scenario | Cost / 1M output tokens | Commodity API price | Verdict |
|---|---|---|---|
| Consumer GPU, realistic home utilisation (10%), hardware amortised | **$2.256** | $0.150 | loses **15×** |
| Consumer GPU, electricity only (hardware treated as sunk), single-stream | **$0.236** | $0.150 | loses 1.6× |
| Consumer GPU, electricity only, saturated with batching | **$0.024** | $0.150 | wins, *if saturated* |

Break-even utilisation for the first row is **unreachable**: even a node generating
tokens 100% of wall-clock time does not amortise the card at $0.15/1M.

The third row is the only one that closes, and it requires the node to be
continuously batched at near-datacentre efficiency. A residential host has neither
the request volume to saturate a GPU nor the ability to keep it saturated, because
what makes their hardware available is precisely that they are not using it.

### The three findings that actually decide it

1. **Hardware amortisation dominates everything else** — roughly $1.73 of the $2.256
   above. Doubling every power and throughput assumption moves the total by under
   50%, which is why the conclusion does not depend on estimates nobody has measured
   (pinned by `test_hardware_amortisation_is_the_dominant_term`). Any pricing that
   recovers the card loses to a commodity API by an order of
   magnitude. Any pricing that does not recover the card is asking hosts to donate
   depreciation and call it earnings.
2. **Idle power is the hidden killer.** A host who leaves a machine on to be
   *available* burns 60–100 W doing nothing. At 10% utilisation the idle draw
   exceeds the inference draw.
3. **Commodity inference prices have collapsed and will not stop.** Competing on
   price against operators with datacentre power contracts and 90% utilisation is
   not a position that improves with effort.

## Decision

**v1 is a donation / mutual-aid network. Credits are an accounting unit, not a
currency, and are explicitly non-redeemable.**

Concretely:

- Metering and the ledger **stay in scope** (ROADMAP 3.2, 3.3). They are needed for
  fairness, quota, abuse investigation and the host's own visibility into what their
  machine did. They were never *only* for payouts.
- **Payouts are out of scope for v1 and are not "v2, coming soon".** No fiat rail,
  no redemption, no exchange rate. This was already on the "deliberately not in v1"
  list; this decision upgrades it from "not yet" to "not this product".
- Every surface that says or implies a host *earns* must be corrected: the dashboard
  says **credits contributed**, not earnings.

## What this costs, stated plainly

- **The most motivating reason to run a node goes away.** "Earn money from your idle
  GPU" recruits strangers; "share compute with people you know" does not. This
  decision shrinks the plausible network dramatically, and that is the honest size.
- **It makes [D1](D1-execution-integrity.md) much easier**, because the incentive to
  cheat mostly evaporates when there is nothing to cash out. That is a real benefit
  and it should not be mistaken for the reason the decision was made.
- If inference prices reverse, or if the target hardware becomes something other
  than consumer GPUs, **re-run the script before re-opening this**.

## What changes in the code

- `scripts/economics.py` + `tests/test_economics.py` — the model, and a test that
  fails if the conclusion changes.
- Ledger and dashboard language: "contributed", never "earned".
- No payout code is written. `CreditLedger` gets wired (3.3) as an accounting record.
