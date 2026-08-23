# experimental/

**Nothing in here is part of the shipped system.** No module under `packages/`
imports it, no application mounts it, and the gate does not run its tests.

This is ROADMAP C2. The code implements features on the "deliberately not in v1"
list — layer sharding and split inference, FP8 activation compression, speculative
decoding, KV-cache checkpointing — which were shipped inside `packages/`, tested by
the same suites as production code, and in two cases **reachable from a running
node**.

## Why quarantine rather than delete

Deleting several thousand lines that work, are tested, and might matter for v2 is not
obviously right. Leaving them where they look like part of the shipped system is what
caused the harm. So they moved, and the boundary is enforced rather than requested:
`tests/test_experimental_is_quarantined.py` fails if `packages/` imports anything
from here.

The autonomous orchestrator was **deleted** instead of moved, because it did not just
sit there — it returned `verification_passed=True` and a report claiming "Closed-loop
tri-factor verification (pytest, ruff, mypy) passed cleanly" for a stub that ran none
of them. There was nothing worth keeping. See ROADMAP 2.10.

## What being here cost, before it was here

The three defects found while doing this move, all of them live, none of them caught
by 664 passing tests:

1. **Every streamed completion was republished onto the Zenoh mesh in plaintext.**
   `node/api/inference.py` built a `BackpressuredStreamRouter` for any request on a
   node with a live session and `put()` each chunk onto
   `public-intelligence/net/transport/stream/{id}` — a key any peer can subscribe to
   with a `**` wildcard, with no subscriber anywhere in the codebase. ROADMAP 2.7
   had spent an entire protocol change AES-256-GCM enveloping *telemetry* on that
   same mesh.

2. **Streaming deadlocked after four chunks.** That same router blocks once
   `sent - acked >= window_size`, and nothing in this repository has ever published
   an ACK. Streaming inference was broken on exactly the deployment this project is
   built for: a node attached to the mesh.

3. **Every node opened an unauthenticated wildcard subscriber at startup.**
   `Runtime._setup_split_stage_listener` subscribed to
   `public-intelligence/net/tasks/*/tensors/*` and, on any matching sample,
   deserialised attacker-controlled bytes and — for a `shm://` payload — read and
   **unlinked host shared memory by attacker-supplied name**. 2.7 authenticated every
   mesh input that changes registry state; this one changed none, so it sat outside
   that scope entirely.

All three existed because cut-feature plumbing was wired into live paths. That is the
argument for this directory, and it is a stronger one than tidiness.

## Running these

```bash
.venv/bin/python -m pytest experimental -q      # 41 tests, not part of the gate
```

They are **collected** by `scripts/verify.sh` and never run. That distinction is the
difference between "not in the gate" and "dead": when this directory was first
created, every one of these 41 tests still imported `node.core.transport` and friends
-- the modules that had just been moved out from under them -- so the whole suite was
unimportable and linting could not tell, because a stale import is valid syntax.
"Kept for v2" had silently become "deleted with extra steps". `--collect-only`
imports each module and reports nothing as passed, so the shipping count stays honest
while an unimportable quarantined test still fails the gate.

## What is here

| Module | Feature | Lines |
|---|---|---|
| `transport.py` | Shared-memory IPC, backpressured tensor streaming | 541 × 2 |
| `local_boundary.py` | Embedding/unembedding across a split boundary — a 120-token vocabulary (116 words + 4 special) against a declared `vocab_size` of 32,000, and seeded `random.gauss` matrices, **not a model** | 378 × 2 |
| `boundary_engine.py` | Re-export shim for the above | 5 × 2 |
| `kv_cache.py` | KV-cache checkpointing and restitching | ~98 × 2 |
| `quantization.py` | FP8/FP4 activation compression | 49 × 2 |
| `consensus.py` | Raft leader election and log replication (scheduler only) | 530 |
| `*/tests/` | The suites covering them | 11 files |

Two copies of each, because Node and Scheduler were separate repositories before the
2026-08-04 monorepo migration. They are duplicated here as they were duplicated there;
converging them is not worth doing for code nothing runs.

## What is NOT here, and why

**`models/sharding.py` and `models/pipeline.py` stay in `packages/`.** `node/backends/base.py`
and `backends/mock.py` import `PipelineStage` and `TensorPayload` from them, and those
are on the live backend interface.

## `consensus.py` moved here on 2026-08-09, and this file was wrong about it

An earlier version of this README said Raft "is inert in practice — the deployment is
a single instance". **That was false, and the correction is the point.**

`ZenohRouter.start()` constructed a `RaftConsensusEngine` and called `start()` on it
on **every Scheduler boot**. When `zenoh.open()` succeeded — which is the normal
case — it:

- opened a **second Zenoh session**, alongside the router's own;
- declared a subscriber on `public-intelligence/net/consensus/*`, a **wildcard key
  with no authentication of any kind**;
- started two background loops (election timeout, heartbeat);
- set `is_active()` True, so the `is_active()` branches in `node_registry`,
  `api/ingress` and `api/openai` were **live**, routing registry writes through Raft
  on a one-node cluster.

The subscriber's handler parsed JSON from anyone and dispatched on a `type` field.
`AppendEntries` with a higher term made the Scheduler a follower of the sender and
appended the sender's entries; `_apply_log_entries` then executed them —
`action: "unregister_node"` **evicting any host**, and `action: "register"`
**injecting one**. An injected node is dispatched to, so it receives other people's
prompts.

ROADMAP 2.7 closed exactly this shape for telemetry, heartbeats and liveliness, and
its own summary named the worst case: *"anyone could evict any host."* It did not
touch the consensus plane. `docs/decisions/D5-decentralisation-claim.md` had already
decided the deployment is a single instance and Raft is out of v1, so there was
nothing an authenticated version of this plane would do. It is no longer constructed,
started, or branched on, and `tests/test_consensus_plane_is_not_open.py` fails if any
of that returns.

## If you are reading this because you want to build on it

Don't, yet. `LocalBoundaryEngine` in particular is a simulation: a 120-token
vocabulary — 116 words plus 4 special tokens, against a declared `vocab_size` of
32,000 — and two seeded random matrices. It produces plausible-looking tensors and
no inference happens. Returning its output to a caller as a completion is precisely
the bug ROADMAP N1 removed, where `token_556` was served as the capital of France
with HTTP 200.
