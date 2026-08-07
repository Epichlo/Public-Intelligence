# Spec: Answer Stage D, and make the project legally usable (ROADMAP D1–D8 + N3)

## What this does

`ROADMAP.md` opens with eight questions the code had been assuming answers to, and
states that nothing in Stages 0–4 should proceed until D1–D3 are settled. This
settles all eight, as written decision records in `docs/decisions/`, and ships the
three files (N3) without which nobody may legally fork, contribute to, or run this.

The decisions are not neutral summaries. Two of them **cut scope that was already on
the roadmap**:

- **D2 finds the economics do not close.** A consumer-GPU host loses ~15× against
  commodity API pricing once hardware amortisation is counted, and break-even
  utilisation is unreachable at any load. So v1 is a **donation network**: credits
  are an accounting unit, payouts are cut, and every surface says *contributed*
  rather than *earned*.
- **D6 finds there is no network and decides not to build one.** The installer
  defaults to `localhost` instead of a domain that does not resolve.

D7 is deliberately **left open**, because it asks for a second party and cannot be
answered by the party asking.

## What actually breaks today

**Nobody may legally use this.** No `LICENSE` means default copyright — all rights
reserved. That contradicts the community-owned positioning outright, and it means the
second pair of eyes D7 asks for could not legally fork the repository to look at it.

**The installer's happy path produces a broken node.** `install.sh` writes
`NODE_BOOTSTRAP_ROUTERS=["tcp/bootstrap.public-intelligence.net:7447"]` — NXDOMAIN —
into every `.env`. The failure is silent and slow rather than immediate.

**Stage 3 is machinery for paying hosts, and hosts cannot profit.** Six roadmap items
were queued behind an economic assumption nobody had checked.

## Design decisions, and why

**Decisions are files with consequences, not prose.** Each record ends with "what
changes in the code". A decision with no consequence in the tree was not really made.
The two that produce code in this change are D2 (`scripts/economics.py`) and D7
(`docs/PREMISES.md`); D1, D4 and D6 produce code in later commits and say so.

**The economics model is a script, not a spreadsheet.** The ROADMAP asked for "one
spreadsheet". A spreadsheet cannot be re-run in CI and cannot notice when it goes
stale — which is the exact failure `CLAUDE.md` records for prose. `tests/test_economics.py`
pins the **conclusion**, not the numbers, so a price update fails only if the answer
changes.

**Every economics input is chosen to favour the host.** High-end commodity price, low
idle draw, generous throughput. A negative result must not be an artefact of
pessimistic assumptions, so a separate test re-runs the verdict with cheap power, a
used card and 3× utilisation.

**Apache-2.0, not MIT.** The patent grant matters for a project touching inference
scheduling, and the explicit warranty disclaimer is the load-bearing legal document
for a self-hosted product with no operator (D3).

**`SECURITY.md` states honest response times for a one-person pre-alpha project**
rather than copying a template promising 24 hours. It also scopes `experimental/` and
`docs/historical/` **out**, with the exception that reaching `experimental/` code from
a running service is itself the vulnerability.

**D7 stays open, and the file says why.** Marking it decided would be the most
on-the-nose possible instance of the problem it names.

**`docs/PREMISES.md` states confidence and falsifiers, including "none available".**
P9 — that describing intentions as achievements is the failure mode — is marked as an
unfalsifiable *belief*, because it drives more process than anything else in the repo
and process justified by an unfalsifiable belief is worth naming as such.

## Done looks like

- [ ] `docs/decisions/` contains D1–D8, each with a decision, its cost, and what
      changes in the code. D7 is marked open.
- [ ] `LICENSE` (Apache-2.0, copyright filled in), `NOTICE`, `SECURITY.md`,
      `CONTRIBUTING.md` exist at the repo root.
- [ ] `docs/OPERATING.md` and `docs/ACCEPTABLE_USE.md` exist, and both state that the
      software enforces none of the policy.
- [ ] `docs/PREMISES.md` exists with a falsifier per premise.
- [ ] `.venv/bin/python scripts/economics.py` runs and prints
      `VERDICT: donation-network`.
- [ ] `tests/test_economics.py` passes, and **was observed failing** under three
      mutations: verdict hardcoded, break-even hardcoded to `None`, amortisation
      dropped.
- [ ] README stops saying the licence is pending and states the narrowed claim.
- [ ] `./scripts/verify.sh` passes.

## Out of scope

- **The code changes the decisions imply.** Invite codes (D1/D4), installer defaults
  (D6/C1), the `experimental/` quarantine (D5/C2), and metering privacy (D3) are each
  their own change with their own spec. This commit is the decisions plus the two
  artefacts they directly produce.
- **Legal review.** D3 is answered for the self-hosted scope only and says in its
  first paragraph that it has not been reviewed by counsel. Operating this as a
  service for other people is gated on that review.
- **Actually obtaining a second pair of eyes.** D7 records what closing it requires;
  it does not close it.
- **Metering the real electricity cost of a real node.** Nobody has, because there is
  no fleet. P3 says so.

## Verification

```
.venv/bin/python scripts/economics.py
.venv/bin/python -m pytest tests/test_economics.py -q
./scripts/verify.sh
```

## Notes / open questions

- **P2 (NAT traversal is the differentiator) is the weakest premise and the one the
  pitch leans on hardest.** It is flagged medium-low confidence in `PREMISES.md`.
- The economics inputs are estimates, not measurements. The conclusion is usable
  anyway because it loses by an order of magnitude and the dominant term is
  amortisation, which no throughput estimate affects — but that is an argument about
  robustness, not about accuracy, and the script says so at the bottom.
