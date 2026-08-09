"""Canary verification catches a node that is not running a model (decision D1).

D1 chose invite-only admission as the primary defence and canaries as the thing that
makes the resulting trust checkable. `docs/OPERATING.md` and `ACCEPTABLE_USE.md` both
said the canary was **not implemented**, which was true and is what this closes.

The tests are organised around what the mechanism is actually for. The `token_556`
class of failure (ROADMAP N1) is a host returning a fixed string, random text, an
empty completion, or an echo -- the shapes a host takes when it wants credit without
spending a GPU. Each gets its own test, because "returns something wrong" is not one
failure mode.

**What is deliberately NOT tested, because it is not claimed:** that the node ran the
model it advertised. A 1B model answers these prompts as well as a 70B one.
`docs/PREMISES.md` P4 records that as a known partial gap.
"""

from __future__ import annotations

import pytest

from scheduler.core.canary import (
    CANARIES,
    Canary,
    CanaryVerifier,
    looks_like_an_echo,
    score,
)

CAPITAL = CANARIES[0]


# --- scoring ---------------------------------------------------------------


@pytest.mark.parametrize(
    "response",
    ["Paris", "paris", "Paris.", "The capital of France is Paris.", "  PARIS  "],
)
def test_a_correct_answer_scores_however_it_is_phrased(response: str) -> None:
    """Scoring must measure correctness, not phrasing.

    An exact-string comparison would fail every model that writes a sentence, so the
    check would quarantine honest nodes -- and a verification mechanism whose false
    positives are worse than the thing it detects gets turned off.
    """
    assert score(CAPITAL, response) is True


@pytest.mark.parametrize(
    "response",
    [
        "",
        "   ",
        "token_556",  # the ROADMAP N1 failure, verbatim
        "London",
        "I cannot answer that.",
        "\n\n",
    ],
)
def test_a_wrong_or_empty_answer_fails(response: str) -> None:
    assert score(CAPITAL, response) is False


def test_a_number_is_matched_on_word_boundaries() -> None:
    """`4` must not be satisfied by `1234`.

    Substring matching would let a host pass the arithmetic canary by returning any
    long digit string, which is exactly the "cheap garbage" case.
    """
    arithmetic = CANARIES[1]
    assert score(arithmetic, "4") is True
    assert score(arithmetic, "The answer is 4.") is True
    assert score(arithmetic, "1234") is False
    assert score(arithmetic, "40") is False


def test_an_echoed_prompt_is_detected_separately_from_scoring() -> None:
    """Echoing is conclusive evidence that no generation happened.

    It needs its own signal because a canary whose accepted word appears in its own
    prompt could otherwise be passed by handing the prompt back.
    """
    assert looks_like_an_echo(CAPITAL.prompt, CAPITAL.prompt) is True
    assert looks_like_an_echo(CAPITAL.prompt, "Paris") is False


def test_an_echo_containing_the_answer_still_fails_the_check() -> None:
    """The case the two signals exist to cover together."""
    trap = Canary("Is the capital of France Paris? Answer yes or no.", ("yes",))
    verifier = CanaryVerifier()

    # The prompt contains "Paris"; echoing it must not count as answering.
    assert verifier.record("n1", trap, trap.prompt) is False


# --- quarantine ------------------------------------------------------------


def test_one_failure_does_not_quarantine() -> None:
    """A single failure is not evidence.

    Greedy decoding is deterministic per model, but tokenisation, quantisation and
    Ollama version differences all move wording. Quarantining on one would make this
    a source of outages rather than a safety mechanism.
    """
    verifier = CanaryVerifier()
    verifier.record("n1", CAPITAL, "London")

    assert verifier.is_quarantined("n1") is False


def test_repeated_failures_quarantine_the_node() -> None:
    verifier = CanaryVerifier(failures_before_quarantine=3)
    for _ in range(3):
        verifier.record("n1", CAPITAL, "token_556")

    assert verifier.is_quarantined("n1") is True


def test_a_success_between_failures_resets_the_run() -> None:
    """Consecutive, not cumulative. A flaky node is not a lying one."""
    verifier = CanaryVerifier(failures_before_quarantine=3)
    verifier.record("n1", CAPITAL, "London")
    verifier.record("n1", CAPITAL, "London")
    verifier.record("n1", CAPITAL, "Paris")
    verifier.record("n1", CAPITAL, "London")

    assert verifier.is_quarantined("n1") is False


def test_a_quarantined_node_is_released_when_it_passes_again() -> None:
    """Recovery must not need an operator.

    A node quarantined by a bad deploy that someone then fixes would otherwise stay
    out of the fleet until a human noticed -- which turns quarantine into a manual
    outage.
    """
    verifier = CanaryVerifier(failures_before_quarantine=2)
    verifier.record("n1", CAPITAL, "token_556")
    verifier.record("n1", CAPITAL, "token_556")
    assert verifier.is_quarantined("n1") is True

    verifier.record("n1", CAPITAL, "Paris")
    assert verifier.is_quarantined("n1") is False


def test_a_node_never_checked_is_not_quarantined() -> None:
    """Unknown is not guilty.

    Quarantining by default would stop a freshly registered node serving until a
    canary had run, turning this into a startup delay. D1 made admission, not
    detection, the primary defence -- this is a smoke detector, not a lock.
    """
    assert CanaryVerifier().is_quarantined("never-seen") is False


def test_quarantine_is_logged_at_error_with_the_evidence(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """This is the operator's only signal that a host is returning text no model made."""
    verifier = CanaryVerifier(failures_before_quarantine=2)
    with caplog.at_level("ERROR"):
        verifier.record("n1", CAPITAL, "token_556")
        verifier.record("n1", CAPITAL, "token_556")

    assert "canary_node_quarantined" in caplog.text
    assert "n1" in caplog.text


# --- bookkeeping -----------------------------------------------------------


def test_history_is_bounded() -> None:
    """Per-node, per-check growth is the rate limiter's C5 bug with a slower clock."""
    verifier = CanaryVerifier()
    for _ in range(verifier.MAX_HISTORY + 25):
        verifier.record("n1", CAPITAL, "Paris")

    assert len(verifier.state_for("n1").history) == verifier.MAX_HISTORY


def test_forgetting_a_node_clears_its_quarantine() -> None:
    """A node that leaves and re-registers must not inherit a stale verdict."""
    verifier = CanaryVerifier(failures_before_quarantine=1)
    verifier.record("n1", CAPITAL, "token_556")
    assert verifier.is_quarantined("n1") is True

    verifier.forget("n1")
    assert verifier.is_quarantined("n1") is False


def test_every_shipped_canary_is_answerable_and_scored() -> None:
    """A canary whose own accepted answer does not score is a permanent false positive.

    It would quarantine every honest node in the fleet, which is the worst thing this
    mechanism could do.
    """
    for canary in CANARIES:
        for accepted in canary.accept:
            assert score(canary, accepted) is True, f"{canary.prompt!r} rejects {accepted!r}"


def test_no_canary_leaks_its_answer_in_its_own_prompt() -> None:
    """A prompt containing its answer can be passed by echoing it.

    `looks_like_an_echo` covers that case, but a canary that depends on the echo
    check to be meaningful is a weak canary -- so the shipped set avoids it.
    """
    for canary in CANARIES:
        prompt_words = set(canary.prompt.lower().replace("?", " ").replace(".", " ").split())
        for accepted in canary.accept:
            assert accepted.lower() not in prompt_words, (
                f"canary {canary.prompt!r} contains its own answer {accepted!r}"
            )


# --- the part that makes it more than bookkeeping --------------------------


def test_a_quarantined_node_is_not_dispatched_to() -> None:
    """Without this the whole mechanism is a log line.

    The matchmaker is where quarantine has to bite, and it is checked BEFORE any
    capability filter -- a node returning `token_556` satisfies every VRAM and model
    requirement perfectly, so ordering the checks the other way would let it through
    on the strength of the lie.
    """
    from scheduler.core.matchmaker import CapabilityMatchmaker
    from scheduler.models.node import GPUInfo, Node
    from scheduler.registry.node_registry import NodeRegistry

    def _node(node_id: str) -> Node:
        return Node(
            node_id=node_id,
            hostname="h",
            ip_address="10.0.0.1",
            region="us-east",
            gpu=GPUInfo(name="RTX 4090", vram_total_gb=24.0, vram_available_gb=20.0),
            cpu_cores=8,
            ram_total_gb=32.0,
            available_models=["llama3"],
        )

    verifier = CanaryVerifier(failures_before_quarantine=1)
    matchmaker = CapabilityMatchmaker(NodeRegistry(), canary=verifier)
    nodes = [_node("good"), _node("liar")]

    assert {n.node_id for n in matchmaker.filter_nodes({"model_name": "llama3"}, nodes)} == {
        "good",
        "liar",
    }

    verifier.record("liar", CAPITAL, "token_556")

    eligible = matchmaker.filter_nodes({"model_name": "llama3"}, nodes)
    assert {n.node_id for n in eligible} == {"good"}


def test_a_matchmaker_without_a_verifier_keeps_the_old_behaviour() -> None:
    """`canary=None` must not start excluding nodes.

    Every pre-D1 test constructs the matchmaker with one argument, and a default
    that quarantined on missing state would fail them all for the wrong reason.
    """
    from scheduler.core.matchmaker import CapabilityMatchmaker
    from scheduler.models.node import GPUInfo, Node
    from scheduler.registry.node_registry import NodeRegistry

    node = Node(
        node_id="n1",
        hostname="h",
        ip_address="10.0.0.1",
        region="us-east",
        gpu=GPUInfo(name="RTX 4090", vram_total_gb=24.0, vram_available_gb=20.0),
        cpu_cores=8,
        ram_total_gb=32.0,
        available_models=["llama3"],
    )
    matchmaker = CapabilityMatchmaker(NodeRegistry())

    assert matchmaker.filter_nodes({"model_name": "llama3"}, [node]) == [node]
