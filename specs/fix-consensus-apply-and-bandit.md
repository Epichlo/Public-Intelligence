# Spec: Fix single-node consensus apply, and gate Bandit at Medium+

## What this does

Fixes a bug where a Raft cluster with no peers appended proposals to its log but
never applied them, so `register` and `unregister_node` were silently dropped on
any single-instance deployment. Also configures CI's Bandit step to gate on
Medium severity and above, and resolves the three Medium findings that gate
surfaced — keeping the intentional `0.0.0.0` binds and annotating them, and
replacing a hardcoded `/tmp` path with the OS temp directory.

## Done looks like

- [ ] With consensus active and zero peers, `register` and `unregister_node`
      actually mutate the registry and `commit_index` advances
- [ ] A platform-independent regression test covers it, observed failing against
      the pre-fix code and passing after
- [ ] `test_zenoh_liveliness_deathrattle` passes on Windows CI
- [ ] `bandit -r ./Node/src ./Scheduler/src -x tests -ll` exits 0
- [ ] `0.0.0.0` remains the default bind for Node and Scheduler, annotated
      `# nosec B104` with the reason
- [ ] The artifact store default path comes from `tempfile.gettempdir()` in both
      duplicate copies (`Node/src/shared/storage/`, `src/shared/storage/`)
- [ ] All three suites pass; CI green on all six legs

## Out of scope

- **The missing auth on the Node control API.** `Node/src/node/api/control.py`
  has no `Depends(...)` on any of its four routes, so `POST /api/v1/node/control`
  (start/stop) and the telemetry and sandbox-log endpoints are unauthenticated
  while bound to `0.0.0.0` on contributor machines. This is the real risk the
  B104 finding sits next to. Recorded here, deliberately not fixed.
- **The 21 remaining Low-severity Bandit findings** (B404/B603/B607 subprocess
  use, B110 try/except/pass around optional hardware probes). Reported by CI but
  not gating.
- **Raft correctness beyond the apply path** — election, log compaction, and
  multi-peer replication are untouched.
- **The `transport.py` / artifact-store duplication itself** — both copies of the
  artifact store were changed in step, but nothing was extracted.

## Verification

```bash
Scheduler/.venv/bin/python -m bandit -r ./Node/src ./Scheduler/src -x tests -ll
Scheduler/.venv/bin/python -m pytest Scheduler/tests -q
Node/.venv/bin/python      -m pytest Node/tests      -q
Node/.venv/bin/python      -m pytest tests           -q
Scheduler/.venv/bin/python -m ruff check ./Scheduler
Node/.venv/bin/python      -m ruff check ./Node
```

## Notes / open questions

- The deathrattle failure was **not** a timing assumption. The CI log showed both
  `zenoh_liveliness_deathrattle_detected` and `zenoh_liveliness_cluster_group_resized`
  firing, meaning the DELETE arrived and `unregister_node()` returned cleanly —
  while the node stayed registered. Windows only decided *which branch* of
  `unregister_node` ran: it could bind an already-listening port, so the consensus
  engine came up active where POSIX failed to open and fell back to direct local
  mutation.
- `_process_deathrattle` logs "cluster_group_resized" unconditionally after the
  await, so the logs claimed success while nothing had changed. Left as-is, but it
  is why this went unnoticed.
- Production impact of the consensus bug: the Render Scheduler is a single
  instance with no peers, the exact configuration that stranded every proposal.
