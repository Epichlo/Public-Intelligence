# Spec: Something outside the process notices (ROADMAP 4.2, the alerting half)

## What this does

`GET /metrics` aggregates what happened. Nothing reads it. An operator still learns
the network broke by looking, which is the half of 4.2 that was left open with the
reason written down: *"something outside the process has to poll and decide, and a
half-built alerter would be worse than none."*

This ships that something: `scripts/watch_scheduler.py`, a standalone poller with no
dependencies beyond the standard library. It reads `/metrics`, applies rules, and
reports state. It runs under cron, systemd, a terminal, or nothing at all.

## Why it is a separate process, and not a background task in the Scheduler

Because the failure an operator most needs to hear about is **the Scheduler being
down**, and a thread inside the Scheduler cannot report that. An in-process alerter
is silent in exactly the case it exists for. That is not a refinement of 4.2's
reasoning — it is 4.2's reasoning, implemented.

## Design decisions, and why

**An empty window is `idle`, never `ok`.** `/metrics` returns
`failure_ratio_in_window: 0.0` when the window holds no requests, because 0/0 is
reported as 0. A naive threshold check therefore calls a network that has served
nothing "perfectly healthy". This is the same defect the website rules forbid —
never render uncertainty as zero — and it is the single most likely way an alerter
lies to you. `idle` is a distinct state, and it is not an alert, because an idle
self-hosted network is normal.

**A rule fires only after N consecutive breaches (default 2).** A one-poll blip that
pages someone trains them to ignore the pager, which is the concrete mechanism by
which a half-built alerter is worse than none. Consecutive-breach counting is the
cheapest honest debounce.

**`high_failure_ratio` requires a minimum sample (default 5).** One failed request
in a window of one is a 100% failure ratio and means nothing.

**Thresholds are arguments, not constants**, so an operator can tune without editing
code — and every one is printed in the output line, so a report is self-describing.

**Output is one JSON object per poll on stdout.** Greppable, pipeable, and it states
the rule set that produced it. No log framework, no config file, no daemon.

**Exit codes are for `--once`**: `0` ok or idle, `1` one or more rules firing,
`2` unreachable. That makes it usable directly as a cron health check.

## Done looks like

- [ ] `scripts/watch_scheduler.py --once` against a live Scheduler prints one JSON
      object and exits 0.
- [ ] Against a stopped Scheduler it exits 2 with `state: "unreachable"` — the case
      an in-process alerter structurally cannot cover.
- [ ] A window with zero requests reports `state: "idle"`, **not** `ok`, and fires
      nothing.
- [ ] `nodes_registered: 0` fires `no_nodes`.
- [ ] A failure ratio over the threshold fires `high_failure_ratio` only once the
      sample floor and the consecutive-breach count are both met.
- [ ] One breach followed by a recovery fires nothing, and resets the counter.
- [ ] A 401 from the Scheduler is reported as `unauthorised`, distinctly from
      `unreachable` — a wrong token must not look like an outage.
- [ ] `tests/test_alerting.py` covers all of the above, each assertion observed
      failing before the implementation.
- [ ] `./scripts/verify.sh` passes, or its failures are pre-existing and named.

## Out of scope

- **Delivery.** No email, Slack, PagerDuty, or webhook. The process prints; a cron
  line or a systemd unit decides what that means. Adding a transport would mean
  credentials, retries, and rate limits — a much larger change wearing this one's
  name.
- **Prometheus exposition.** 4.2 already recorded why the endpoint is JSON, and that
  reasoning is unchanged.
- **Alert history or state persistence across runs.** Consecutive-breach counting
  lives in memory for the lifetime of one `--watch` process. A cron-driven `--once`
  therefore cannot debounce, and the `--once` output says so rather than implying a
  memory it does not have.

## Verification

```
.venv/bin/python -m pytest tests/test_alerting.py -q
.venv/bin/python scripts/watch_scheduler.py --once --url http://127.0.0.1:9 --token x
./scripts/verify.sh
```

## Notes / open questions

- **It has never run against a real Scheduler under real load**, because no such
  deployment exists (D6 — there is no network, by decision). The rules are tested
  against synthesised `/metrics` payloads, which is honest but is not the same thing.
- The sample floor and breach count are guesses. They are arguments precisely
  because nobody has data to justify a default yet.
