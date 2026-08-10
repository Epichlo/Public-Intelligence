#!/usr/bin/env python3
"""Poll `/metrics` and decide whether something is wrong (ROADMAP 4.2, alerting half).

4.2 shipped aggregation and stopped there, with the reason written down: *something
outside the process has to poll and decide, and a half-built alerter would be worse
than none.* This is that something.

**It is a separate process on purpose.** The failure an operator most needs to hear
about is the Scheduler being down, and a background task inside the Scheduler cannot
report that -- it is silent in exactly the case it exists for.

Stdlib only, no daemon, no config file, no delivery transport. It prints one JSON
object per poll; a cron line or a systemd unit decides what that means.

    scripts/watch_scheduler.py --once --url http://localhost:8000 --token "$TOKEN"
    scripts/watch_scheduler.py --watch --interval 60 --url ... --token ...

Exit codes (`--once`): 0 ok or idle, 1 a rule is firing, 2 unreachable or refused.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

OK = 0
FIRING = 1
UNREACHABLE = 2


@dataclass(frozen=True)
class Thresholds:
    """Every default here is a guess, which is why they are all arguments.

    Nobody has run this against a real fleet under real load -- there is no fleet
    (D6). Numbers chosen by taste are labelled as such rather than presented as
    tuning.
    """

    failure_ratio: float = 0.25
    # One failure out of one request is a 100% failure ratio and means nothing.
    min_sample: int = 5
    # Consecutive breaches before a ratio rule fires. A single-poll blip that pages
    # someone is the concrete mechanism by which an alerter becomes background noise.
    consecutive: int = 2


@dataclass
class Result:
    state: str
    firing: list[str] = field(default_factory=list)
    breaches: dict[str, int] = field(default_factory=dict)
    detail: dict[str, object] = field(default_factory=dict)


def classify_http_error(status: int) -> str:
    """A rejected credential and a dead server are different problems.

    Collapsing them sends an operator to restart a service that was never down.
    """
    if status in (401, 403):
        return "unauthorised"
    return "unreachable"


def evaluate(
    metrics: dict[str, object],
    thresholds: Thresholds,
    breaches: dict[str, int],
) -> Result:
    """Apply the rules to one `/metrics` payload.

    `breaches` carries the consecutive-breach counters between polls. It is read, not
    mutated: a caller holding the previous Result must be able to compare.
    """
    counters = dict(breaches)
    firing: list[str] = []

    requests = int(metrics.get("requests_in_window") or 0)
    nodes = int(metrics.get("nodes_registered") or 0)
    ratio = float(metrics.get("failure_ratio_in_window") or 0.0)

    # Not debounced. Unlike a ratio this is a binary fact rather than a noisy
    # measurement, and there is no reading of "zero nodes registered" that resolves
    # itself on the next poll without something having changed.
    if nodes == 0:
        firing.append("no_nodes")

    # The sample floor and the debounce both guard this rule, in that order.
    breached = requests >= thresholds.min_sample and ratio >= thresholds.failure_ratio
    counters["high_failure_ratio"] = counters.get("high_failure_ratio", 0) + 1 if breached else 0
    if counters["high_failure_ratio"] >= thresholds.consecutive:
        firing.append("high_failure_ratio")

    # An empty window reports failure_ratio 0.0, because 0/0 is rendered as 0. Calling
    # that `ok` would mean a network that has served nothing reads as flawless -- the
    # same defect the website rules forbid: never render uncertainty as zero. An idle
    # self-hosted network is normal, so `idle` is a state and not an alert.
    if firing:
        state = "alerting"
    elif requests == 0:
        state = "idle"
    else:
        state = "ok"

    return Result(
        state=state,
        firing=firing,
        breaches=counters,
        detail={
            "nodes_registered": nodes,
            "requests_in_window": requests,
            "failure_ratio_in_window": ratio,
            "thresholds": {
                "failure_ratio": thresholds.failure_ratio,
                "min_sample": thresholds.min_sample,
                "consecutive": thresholds.consecutive,
            },
        },
    )


def fetch(url: str, token: str, timeout: float) -> tuple[dict[str, object] | None, str | None]:
    """Return (metrics, error_state). Exactly one of the two is None."""
    request = urllib.request.Request(
        url.rstrip("/") + "/metrics",
        headers={"X-Network-Auth-Token": token},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return payload, None
    except urllib.error.HTTPError as exc:
        return None, classify_http_error(exc.code)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None, "unreachable"


def poll(
    url: str, token: str, timeout: float, thresholds: Thresholds, breaches: dict[str, int]
) -> Result:
    metrics, error = fetch(url, token, timeout)
    if error is not None or metrics is None:
        # Deliberately does NOT reset the breach counters: an outage in the middle of
        # a degradation is a continuation of it, not a recovery.
        return Result(state=error or "unreachable", breaches=dict(breaches))
    return evaluate(metrics, thresholds, breaches)


def _emit(result: Result, *, once: bool) -> None:
    line: dict[str, object] = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "state": result.state,
        "firing": result.firing,
        **result.detail,
    }
    if once:
        line["note"] = (
            "single poll: no debounce is possible across runs, so a ratio rule "
            "needing consecutive breaches cannot fire here. Use --watch for that."
        )
    print(json.dumps(line), flush=True)


def _exit_code(result: Result) -> int:
    if result.state in ("unreachable", "unauthorised"):
        return UNREACHABLE
    return FIRING if result.firing else OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8000", help="Scheduler base URL")
    parser.add_argument("--token", default="", help="fleet credential (X-Network-Auth-Token)")
    parser.add_argument("--once", action="store_true", help="poll once and exit")
    parser.add_argument("--watch", action="store_true", help="poll forever")
    parser.add_argument("--interval", type=float, default=60.0, help="seconds between polls")
    parser.add_argument("--timeout", type=float, default=10.0, help="per-request timeout")
    parser.add_argument("--failure-ratio", type=float, default=Thresholds.failure_ratio)
    parser.add_argument("--min-sample", type=int, default=Thresholds.min_sample)
    parser.add_argument("--consecutive", type=int, default=Thresholds.consecutive)
    args = parser.parse_args(argv)

    thresholds = Thresholds(
        failure_ratio=args.failure_ratio,
        min_sample=args.min_sample,
        consecutive=args.consecutive,
    )

    if not args.watch:
        result = poll(args.url, args.token, args.timeout, thresholds, {})
        _emit(result, once=True)
        return _exit_code(result)

    breaches: dict[str, int] = {}
    while True:
        result = poll(args.url, args.token, args.timeout, thresholds, breaches)
        breaches = result.breaches
        _emit(result, once=False)
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
