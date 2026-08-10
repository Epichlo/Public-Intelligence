"""The half of ROADMAP 4.2 that decides something is wrong.

`GET /metrics` aggregates. Until now nothing read it, so an operator still learned
that the network had broken by looking at it.

The rule that matters most here is the one about an empty window. `/metrics` reports
`failure_ratio_in_window: 0.0` when it holds no requests at all, because 0/0 is
rendered as 0 -- so the naive threshold check calls a network that has served nothing
"perfectly healthy". Every test below that mentions `idle` exists because of that.

See `specs/something-outside-the-process-notices.md`.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WATCHER = REPO_ROOT / "scripts" / "watch_scheduler.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _metrics(**overrides: object) -> dict[str, object]:
    """A `/metrics` payload shaped like the real endpoint's."""
    payload: dict[str, object] = {
        "window": "recent",
        "window_size": 200,
        "nodes_registered": 3,
        "requests_in_window": 100,
        "requests_failed_in_window": 1,
        "failure_ratio_in_window": 0.01,
        "prompt_tokens_in_window": 5000,
        "completion_tokens_in_window": 9000,
        "requests_by_node_in_window": {"node-a": 60, "node-b": 40},
    }
    payload.update(overrides)
    return payload


def test_the_watcher_exists() -> None:
    assert WATCHER.exists(), "scripts/watch_scheduler.py is missing"


# ---------------------------------------------------------------------------
# The rules
# ---------------------------------------------------------------------------


def test_a_healthy_window_is_ok() -> None:
    from watch_scheduler import Thresholds, evaluate  # type: ignore[import-not-found]

    result = evaluate(_metrics(), Thresholds(), breaches={})
    assert result.state == "ok", result
    assert not result.firing


def test_an_empty_window_is_idle_not_ok() -> None:
    """0/0 renders as 0.0, which reads as a flawless success rate.

    A network that has served nothing is not healthy and is not broken. Calling it
    `ok` is the specific lie this watcher must not tell; `idle` is a third answer.
    """
    from watch_scheduler import Thresholds, evaluate  # type: ignore[import-not-found]

    result = evaluate(
        _metrics(requests_in_window=0, requests_failed_in_window=0, failure_ratio_in_window=0.0),
        Thresholds(),
        breaches={},
    )
    assert result.state == "idle", f"an empty window reported {result.state!r}"
    assert not result.firing, "an idle network must not page anyone"


def test_no_registered_nodes_fires() -> None:
    """Nothing can be served. This is true even when the window is empty."""
    from watch_scheduler import Thresholds, evaluate  # type: ignore[import-not-found]

    result = evaluate(
        _metrics(nodes_registered=0, requests_in_window=0, failure_ratio_in_window=0.0),
        Thresholds(),
        breaches={},
    )
    assert "no_nodes" in result.firing, result


def test_a_high_failure_ratio_fires_once_debounced() -> None:
    from watch_scheduler import Thresholds, evaluate  # type: ignore[import-not-found]

    payload = _metrics(requests_failed_in_window=60, failure_ratio_in_window=0.6)
    thresholds = Thresholds(failure_ratio=0.25, min_sample=5, consecutive=2)

    first = evaluate(payload, thresholds, breaches={})
    assert not first.firing, "a single breach must not fire -- that is the flap"
    assert first.breaches["high_failure_ratio"] == 1

    second = evaluate(payload, thresholds, breaches=first.breaches)
    assert "high_failure_ratio" in second.firing, "a sustained breach must fire"


def test_a_recovery_resets_the_breach_counter() -> None:
    """One bad poll then a good one is not an incident."""
    from watch_scheduler import Thresholds, evaluate  # type: ignore[import-not-found]

    thresholds = Thresholds(failure_ratio=0.25, min_sample=5, consecutive=2)
    bad = evaluate(
        _metrics(requests_failed_in_window=60, failure_ratio_in_window=0.6),
        thresholds,
        breaches={},
    )
    good = evaluate(_metrics(), thresholds, breaches=bad.breaches)

    assert not good.firing
    assert good.breaches.get("high_failure_ratio", 0) == 0, (
        "the counter survived a recovery, so unrelated blips would accumulate into a page"
    )


def test_a_tiny_sample_cannot_fire_the_ratio_rule() -> None:
    """One failure out of one request is a 100% failure ratio and means nothing."""
    from watch_scheduler import Thresholds, evaluate  # type: ignore[import-not-found]

    thresholds = Thresholds(failure_ratio=0.25, min_sample=5, consecutive=1)
    result = evaluate(
        _metrics(requests_in_window=1, requests_failed_in_window=1, failure_ratio_in_window=1.0),
        thresholds,
        breaches={},
    )
    assert "high_failure_ratio" not in result.firing, result


# ---------------------------------------------------------------------------
# The states an in-process alerter structurally cannot report
# ---------------------------------------------------------------------------


def _run_once(url: str) -> tuple[int, dict[str, object]]:
    proc = subprocess.run(
        [sys.executable, str(WATCHER), "--once", "--url", url, "--token", "t"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        check=False,
    )
    line = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "{}"
    return proc.returncode, json.loads(line)


def test_an_unreachable_scheduler_is_reported_and_exits_two() -> None:
    """The whole reason this is a separate process.

    A thread inside the Scheduler cannot tell you the Scheduler is down. Port 9 is
    the discard port: reliably closed, no network required to prove it.
    """
    code, payload = _run_once("http://127.0.0.1:9")
    assert payload.get("state") == "unreachable", payload
    assert code == 2, f"expected exit 2 for an outage, got {code}"


def test_the_once_output_states_it_cannot_debounce() -> None:
    """A cron-driven single poll has no memory, and must not imply that it does."""
    _code, payload = _run_once("http://127.0.0.1:9")
    assert "note" in payload, payload
    assert "debounce" in str(payload["note"]).lower(), payload


@pytest.mark.parametrize("status_code", [401, 403])
def test_a_rejected_token_is_not_reported_as_an_outage(status_code: int) -> None:
    """A wrong credential and a dead server are different problems.

    Collapsing them sends an operator to restart a service that was never down.
    """
    from watch_scheduler import classify_http_error  # type: ignore[import-not-found]

    assert classify_http_error(status_code) == "unauthorised"


def test_a_server_error_is_not_reported_as_unauthorised() -> None:
    from watch_scheduler import classify_http_error  # type: ignore[import-not-found]

    assert classify_http_error(500) == "unreachable"
