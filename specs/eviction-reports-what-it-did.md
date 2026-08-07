# Spec: Eviction reports what it did (ROADMAP 2.5)

## What this does

A node leaving the registry is currently announced whether or not it left. This
makes the removal paths return what actually happened, and log that instead of an
assumption.

## What actually breaks today

ROADMAP 2.5 has been open since before 2.7 and its text was already wrong once —
it claimed stale-eviction existed when nothing aged nodes out at all. 2.7 built
that mechanism. What survives is the original complaint, in its remaining form:

```python
await self.registry.unregister_node(node_id)
self._last_verified_heartbeat.pop(node_id, None)
logger.info("zenoh_node_evicted_stale", node_id=node_id, ...)
```

`unregister_node` returns `None`. It cannot fail loudly and it cannot report a
no-op, so the `logger.info` above fires unconditionally — it is an announcement
that the *call was made*, dressed as a statement that the node was evicted.

Three ways that diverges from the truth:

1. **The consensus path never touches the registry.** `unregister_node` proposes
   `("unregister_node", …)` to the engine when one is active and returns
   immediately. Whether the proposal was ever applied is unknown to the caller,
   which logs the eviction as done regardless.
2. **`local_unregister_node` is "safe if not present"** — it `pop`s with defaults
   and discards, so removing a node that was never there is indistinguishable from
   removing one that was.
3. **The graceful path logs nothing at all.** `DELETE /nodes/{id}` removes a node
   and says nothing, so the two ways a node can leave are asymmetric: one
   over-reports, the other under-reports.

The operator-visible consequence is small but exactly the kind this repo cares
about: the logs cannot answer "did that node actually go, and why".

## Design decisions, and why

**The removal methods return whether the node was actually removed.**
`local_unregister_node` returns `True` only when the node was present. That is the
smallest change that lets a caller stop guessing.

**On the consensus path, truth is established by re-checking, not by assuming.**
`unregister_node` cannot know whether a proposal applied, so it does not claim to:
it reports whether the node is absent *afterwards*. That is a weaker statement than
"I removed it" and it is the true one. (The consensus engine is not part of v1 —
single instance is the deployment — so this path is unexercised in practice. It is
handled anyway because the failure mode is a false log, which is the whole subject
of this change.)

**A no-op eviction logs at WARNING, not INFO.** Being asked to evict a node that is
not there means something upstream held a stale view. That is worth seeing.

**The graceful path gains a log line.** Both exits now say a node left and which
route it took, so "where did node X go" has an answer in one grep rather than an
inference from absence.

**No new endpoint, no eviction history.** An operator-facing audit trail of
departures would be a feature; this is a correctness fix to what is already
claimed. Recorded under Out of scope so the difference is deliberate.

## Done looks like

- [x] `local_unregister_node` returns `True` when it removed a node and `False`
      when the node was not present. Covered by a test.
- [x] `unregister_node` returns the same, and on the consensus path reports
      whether the node is absent afterwards rather than assuming the proposal
      applied. Covered by a test with an active fake engine that ignores proposals.
- [x] `_evict_if_stale` logs `zenoh_node_evicted_stale` **only** when the node was
      really removed, and logs a warning when it was not. Covered by two tests.
- [x] `DELETE /nodes/{id}` logs the departure. Covered by a test.
- [x] `./scripts/verify.sh` passes.

## Out of scope

- **An eviction history or a departures endpoint.** A feature, not a correction.
- **Making the consensus engine correct.** It is explicitly not in v1. This change
  only stops the caller lying about its outcome.
- **Alerting on evictions.** ROADMAP 4.2 (operational visibility).
- **Why a node went stale.** The sweep records that a node stopped heartbeating,
  not the cause; distinguishing "host powered off" from "network partition" is not
  something the Scheduler can know.

## Verification

```
./scripts/verify.sh
.venv/bin/python -m pytest packages/scheduler/tests/test_eviction_reporting.py -q
```

## Notes / open questions

- Duplicate-module check: `NodeRegistry` exists only in `packages/scheduler`. No
  twin.
- This is the second time 2.5's roadmap text has been corrected. The first said a
  mechanism existed that did not; this one narrows what remains to the single
  surviving defect. Worth noting that a line left open for several roadmap items
  accumulated two wrong claims.
