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

## What is here

| Module | Feature | Lines |
|---|---|---|
| `transport.py` | Shared-memory IPC, backpressured tensor streaming | 541 × 2 |
| `local_boundary.py` | Embedding/unembedding across a split boundary — a 155-word vocabulary and seeded `random.gauss` matrices, **not a model** | 378 × 2 |
| `boundary_engine.py` | Re-export shim for the above | 5 × 2 |
| `kv_cache.py` | KV-cache checkpointing and restitching | ~98 × 2 |
| `quantization.py` | FP8/FP4 activation compression | 49 × 2 |
| `*/tests/` | The suites covering them | 10 files |

Two copies of each, because Node and Scheduler were separate repositories before the
2026-08-04 monorepo migration. They are duplicated here as they were duplicated there;
converging them is not worth doing for code nothing runs.

## What is NOT here, and why

**`consensus.py` (Raft, 530 lines) stays in `packages/scheduler`.** It is genuinely
wired: `zenoh_router.py` constructs a `RaftConsensusEngine`, and `node_registry.py`,
`api/ingress.py` and `api/openai.py` all branch on `consensus_engine.is_active()`.
Extracting it is a real refactor on a live dispatch path, not a file move, and doing
it blind alongside three security fixes would be the kind of change that breaks
something quietly. It is inert in practice — the deployment is a single instance
([D5](../docs/decisions/D5-decentralisation-claim.md)) — and it is tracked as
remaining C2 work rather than claimed as done.

**`models/sharding.py` and `models/pipeline.py` stay.** `node/backends/base.py` and
`backends/mock.py` import `PipelineStage` and `TensorPayload` from them, and those
are on the live backend interface.

## If you are reading this because you want to build on it

Don't, yet. `LocalBoundaryEngine` in particular is a simulation: a 155-word
vocabulary and two seeded random matrices. It produces plausible-looking tensors and
no inference happens. Returning its output to a caller as a completion is precisely
the bug ROADMAP N1 removed, where `token_556` was served as the capital of France
with HTTP 200.
