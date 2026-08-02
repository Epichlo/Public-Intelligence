# Spec: Fix the first CI run's failures

## What this does

The workspace repo's CI executed for the first time on 2026-08-02 and failed on
all six matrix legs: a ruff `E501` on every POSIX leg, and 8 test failures on both
Windows legs. This fixes the lint error, fixes two genuine bugs the Windows legs
exposed (a clock-based LRU that evicts the wrong entry, and shared memory that is
destroyed before it can be read on Windows), and marks the remaining 5 tests as
POSIX-only where that is the correct classification rather than a workaround.

## Done looks like

- [ ] `ruff check ./Node ./Scheduler` and `ruff format --check` pass clean
- [ ] `RadixTrieCache` evicts by true recency with no clock involved — eviction is
      correct even when every operation lands on the same timer tick
- [ ] `SharedMemoryIPC.write_data` produces a block that is still readable
      afterwards on Windows as well as POSIX; `cleanup` releases it on both
- [ ] The `SharedMemoryIPC` implementations in `Node/.../transport.py` and
      `Scheduler/.../transport.py` remain byte-identical (they are a known
      duplicate pair)
- [ ] 4 installer tests and 1 Docker-sandbox test are skipped on `win32` with a
      comment explaining why that is correct, not a workaround
- [ ] All three suites pass locally; CI goes green on all six legs

## Out of scope

- **The pre-existing duplication itself.** `transport.py` is duplicated between
  Node and Scheduler; this change keeps both copies in sync but does not extract
  a shared package.
- **Docstring/formatting drift elsewhere in the two `transport.py` copies** —
  pre-existing, outside the `SharedMemoryIPC` region, left alone.
- **The `install.ps1`-runs-for-real CI step** on the Windows legs.
- **`TELEMETRY_SECRET_KEY`, CORS wildcard, `/v1/batch` having no auth** — all
  known, all untouched.

## Verification

```bash
Scheduler/.venv/bin/python -m ruff check ./Scheduler
Node/.venv/bin/python      -m ruff check ./Node
Scheduler/.venv/bin/python -m pytest Scheduler/tests -q
Node/.venv/bin/python      -m pytest Node/tests      -q
Node/.venv/bin/python      -m pytest tests           -q
diff <(sed -n '1,108p' Node/src/node/core/transport.py) \
     <(sed -n '1,108p' Scheduler/src/scheduler/core/transport.py)   # only docstring + import
```

## Notes / open questions

- The LRU bug was **not** Windows-specific. `time.time()` ties are possible on any
  platform under rapid access, and it is a wall clock that can step backwards
  under NTP correction. Windows' ~15.6ms granularity only made it deterministic
  enough to catch. Fixed by removing the clock entirely (`OrderedDict` ordering).
- Shared memory blocks whose `cleanup()` is never called now stay resident for the
  life of the process rather than being destroyed early on Windows. Callers already
  owned that release; the leak surface is unchanged on POSIX.
- Windows CI has never been green, so these are first-observation failures, not
  regressions.
