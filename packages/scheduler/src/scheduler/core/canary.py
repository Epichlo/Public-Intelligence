"""Canary verification: is this node running a model at all? (decision D1)

D1 chose invite-only admission as the primary defence and this as the mechanism that
makes the resulting trust **checkable rather than assumed**. A canary is a prompt with
a deterministic, low-entropy answer, dispatched down the ordinary inference path at
`temperature=0` and scored against what a working model would say.

## What this proves, and what it does not

**It proves a node is running a model.** It catches the `token_556` class of failure
(ROADMAP N1) — a host returning a fixed string, random text, an empty completion, or
an echo of the prompt — which is exactly the shape a host takes when it wants credit
without spending a GPU.

**It does not prove the node ran the model it claimed.** A 1B model answers "What is
the capital of France?" as well as a 70B one. `docs/PREMISES.md` P4 states this as a
known partial gap rather than a solved problem, and nothing here should be read as
attestation.

That asymmetry is why quarantine is the response and not, say, a reputation score:
the signal is reliable in one direction only. A node that fails canaries is broken or
lying; a node that passes them has merely not been caught.

## Why the thresholds are what they are

**Consecutive failures, not a ratio.** A single failure is not evidence: greedy
decoding is deterministic per model, but tokenisation, quantisation and Ollama
version differences all move wording. Requiring a run of them means an honest node
has to fail repeatedly, which a transient does not do.

**Recovery is automatic on the next pass.** A node quarantined by a bad deploy that
someone then fixes must not need an operator to notice and intervene, or quarantine
becomes a manual outage rather than a safety mechanism.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Canary:
    """A prompt whose answer a working model of any size will contain."""

    prompt: str
    # Any one of these appearing (case-insensitively) counts as correct. Several
    # accepted spellings rather than one exact string, because scoring generated
    # text against a single expected answer measures phrasing, not correctness.
    accept: tuple[str, ...]


# Deliberately mundane, deliberately short, and deliberately not about this project.
# A prompt a host could recognise as a canary is a prompt a host can special-case.
CANARIES: tuple[Canary, ...] = (
    Canary("What is the capital of France? Answer with one word.", ("paris",)),
    Canary("What is 2 + 2? Answer with one number.", ("4", "four")),
    Canary("Complete: the opposite of hot is ___. One word.", ("cold",)),
    Canary("What colour is the clear daytime sky? One word.", ("blue",)),
)

_WORD = re.compile(r"[a-z0-9]+")


def score(canary: Canary, response: str) -> bool:
    """True when `response` plausibly answers `canary`.

    Matched on word boundaries rather than substrings: `"4"` must not be satisfied
    by `"1234"`, and `"paris"` should be by `"Paris."` A host returning a long essay
    that happens to contain the word still passes, which is the correct trade -- the
    failure being detected is a node that is not running a model, not one that is
    verbose.
    """
    if not response or not response.strip():
        return False
    words = set(_WORD.findall(response.lower()))
    return any(term.lower() in words for term in canary.accept)


def looks_like_an_echo(prompt: str, response: str) -> bool:
    """True when the response is mostly the prompt handed back.

    A separate signal from `score`, because a node that echoes could accidentally
    pass a canary whose accepted word appears in the prompt -- and echoing is itself
    conclusive evidence that no generation happened.
    """
    if not response:
        return False
    prompt_words = set(_WORD.findall(prompt.lower()))
    response_words = _WORD.findall(response.lower())
    if not response_words:
        return False
    overlap = sum(1 for w in response_words if w in prompt_words)
    return overlap / len(response_words) > 0.8


@dataclass
class NodeCanaryState:
    """What canary checks have found about one node."""

    consecutive_failures: int = 0
    passes: int = 0
    failures: int = 0
    quarantined: bool = False
    last_checked_at: float = 0.0
    last_detail: str = ""
    history: list[bool] = field(default_factory=list)


class CanaryVerifier:
    """Runs canary checks and quarantines nodes that fail them."""

    # Three in a row. One is noise; two could still be a bad prompt interacting with
    # a small model; three is a pattern. Configurable, but the default is the one an
    # operator gets and so is the one that has to be defensible.
    DEFAULT_FAILURES_BEFORE_QUARANTINE = 3
    MAX_HISTORY = 50

    def __init__(self, failures_before_quarantine: int | None = None) -> None:
        self.failures_before_quarantine = (
            failures_before_quarantine or self.DEFAULT_FAILURES_BEFORE_QUARANTINE
        )
        self._state: dict[str, NodeCanaryState] = {}

    def state_for(self, node_id: str) -> NodeCanaryState:
        return self._state.setdefault(node_id, NodeCanaryState())

    def is_quarantined(self, node_id: str) -> bool:
        """Whether dispatch should skip this node.

        Defaults to False for a node never checked. Quarantining the unknown would
        mean a fresh node cannot serve until a canary has run, which turns this from
        a safety mechanism into a startup delay -- and D1 made admission, not
        detection, the primary defence.
        """
        state = self._state.get(node_id)
        return bool(state and state.quarantined)

    def record(self, node_id: str, canary: Canary, response: str) -> bool:
        """Score one canary reply, update state, and return whether it passed."""
        echoed = looks_like_an_echo(canary.prompt, response)
        passed = score(canary, response) and not echoed

        state = self.state_for(node_id)
        state.last_checked_at = time.time()
        state.history.append(passed)
        del state.history[: -self.MAX_HISTORY]

        if passed:
            state.passes += 1
            state.consecutive_failures = 0
            state.last_detail = "ok"
            if state.quarantined:
                # Automatic recovery. A node quarantined by a bad deploy that
                # someone then fixed must not wait for an operator to notice.
                state.quarantined = False
                logger.info("canary_node_released: node_id=%s", node_id)
            return True

        state.failures += 1
        state.consecutive_failures += 1
        state.last_detail = "echoed the prompt" if echoed else "wrong or empty answer"

        if state.consecutive_failures >= self.failures_before_quarantine and not state.quarantined:
            state.quarantined = True
            # ERROR, not WARNING: this is the operator's only signal that a host in
            # their own fleet is returning text no model produced.
            logger.error(
                "canary_node_quarantined: node_id=%s consecutive_failures=%d detail=%s",
                node_id,
                state.consecutive_failures,
                state.last_detail,
            )
        else:
            logger.warning(
                "canary_check_failed: node_id=%s consecutive_failures=%d detail=%s",
                node_id,
                state.consecutive_failures,
                state.last_detail,
            )
        return False

    def forget(self, node_id: str) -> None:
        """Drop state for a node that has left the fleet."""
        self._state.pop(node_id, None)

    def summary(self) -> dict[str, dict[str, object]]:
        """Operator view: which nodes are quarantined and on what evidence."""
        return {
            node_id: {
                "quarantined": state.quarantined,
                "passes": state.passes,
                "failures": state.failures,
                "consecutive_failures": state.consecutive_failures,
                "last_checked_at": state.last_checked_at,
                "last_detail": state.last_detail,
            }
            for node_id, state in self._state.items()
        }
