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

import asyncio
import contextlib
import logging
import re
import time
from dataclasses import dataclass, field

from scheduler.core.node_dispatch import NodeDispatchError, infer_once
from scheduler.registry.node_registry import NodeRegistry

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


class CanaryProber:
    """Dispatches live canaries down the ordinary inference path, on a slow cadence.

    `CanaryVerifier.record` is the scoring half of decision D1; this class is the
    dispatch half, without which quarantine can structurally never flip -- nothing
    else in the process ever scores a node's reply against a canary. One node is
    probed per tick, round-robin over the whole registry (quarantined nodes
    included: they are how a fixed node earns its way back in), and the prompt
    travels through the SAME `infer_once` path real completions use -- mesh when
    the node has been seen there, HTTP otherwise. A canary that travelled a
    special road would verify the road, not the node.

    Failure-safety, stated as rules:

    - A dispatch failure is NOT canary evidence. A node that cannot be reached is
      the staleness sweep's problem; quarantining on transport errors would evict
      nodes for being offline, which is the availability surface degrading, not a
      lie being caught.
    - Anything this class raises is caught by its own loop and logged. Canary
      infrastructure must never take dispatch down with it.
    - Quarantine flips only inside `record`, on a scored reply.
    """

    def __init__(
        self,
        registry: NodeRegistry,
        verifier: CanaryVerifier,
        *,
        settings: object,
        mesh_client: object | None,
        interval: float,
    ) -> None:
        """Build the prober. Call `start()` from a running event loop.

        Args:
            registry: Where the live nodes are listed from.
            verifier: The D1 scorer whose `record` turns replies into quarantine.
            settings: Scheduler settings; passed through to `infer_once` for the
                HTTP fallback path.
            mesh_client: The Zenoh mesh client real dispatch uses, or None when
                the Scheduler has no session. None is normal: dispatch then
                falls back to HTTP.
            interval: Seconds between probes. Zero or negative disables probing.
        """
        self._registry = registry
        self._verifier = verifier
        self._settings = settings
        self._mesh_client = mesh_client
        self.interval = interval
        self._node_cursor = 0
        self._canary_cursor = 0
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """Start the probe loop. A no-op when disabled or already running."""
        if self._task is not None:
            return
        if self.interval <= 0:
            logger.info("canary_prober_disabled: interval=%s", self.interval)
            return
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        """Cancel the probe loop and wait for it to finish. Idempotent."""
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def _loop(self) -> None:
        """Probe one node per tick, forever. One bad tick must not end the loop."""
        while True:
            await asyncio.sleep(self.interval)
            try:
                await self.check_one_node()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("canary_probe_failed_unexpectedly")

    async def check_one_node(self) -> bool:
        """Probe the next node in rotation. Returns whether the reply PASSED.

        Every early return here is a tick where nothing was learned: an empty
        fleet, a node with no model to ask about, or a node that could not be
        reached. None of those is evidence of dishonesty, so none of them
        touches the verifier.
        """
        nodes = await self._registry.list()
        if not nodes:
            return False

        node = nodes[self._node_cursor % len(nodes)]
        self._node_cursor = (self._node_cursor + 1) % len(nodes)

        if not node.available_models:
            logger.debug("canary_probe_skipped_no_models: node_id=%s", node.node_id)
            return False

        # Rotate through the shipped canaries so a host cannot tune itself to one
        # prompt it has learned to answer.
        canary = CANARIES[self._canary_cursor % len(CANARIES)]
        self._canary_cursor = (self._canary_cursor + 1) % len(CANARIES)

        try:
            result = await infer_once(
                registry=self._registry,
                settings=self._settings,
                mesh_client=self._mesh_client,
                node_id=node.node_id,
                ip_address=node.ip_address,
                model=node.available_models[0],
                prompt=canary.prompt,
            )
        except NodeDispatchError as e:
            logger.warning(
                "canary_dispatch_failed_not_evidence: node_id=%s status=%s error=%s",
                node.node_id,
                e.status,
                e.detail,
            )
            return False

        passed = self._verifier.record(node.node_id, canary, result.get("response", ""))
        logger.info("canary_probe_recorded: node_id=%s passed=%s", node.node_id, passed)
        return passed
