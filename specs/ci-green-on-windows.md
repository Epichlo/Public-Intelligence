# Spec: CI green on Windows, and the coarse-clock credit bug behind it

## What this does

CI has been red on `main` since 2026-08-09 — including on the `v1.0.0` release
commit `39f0227` and on HEAD `b31fce3` — and the failure is **Windows-only**:
Ubuntu, macOS and the fresh-clone job are green on all of them. Two checks fail
on all three Windows legs (Python 3.11 / 3.12 / 3.14), and one of the two is a
real defect in shipped code rather than a test or environment artefact.

1. **`shellcheck`** rejects `install.sh` with `SC1017 (Literal carriage return)`
   plus a cascade of here-document parse errors (`SC1073`, `SC1041`, `SC1042`,
   `SC1072`) at lines 395–397 and 608. The file is LF-clean in the repository —
   there is no `.gitattributes`, so `actions/checkout` on Windows applies the
   runner's `core.autocrlf=true` and rewrites every `.sh` file to CRLF on
   checkout. shellcheck is correct to reject the result: a CRLF here-document
   terminator genuinely does not match its opener.

2. **Two metering tests fail `assert 0.0 > 0.0`** — a host that served a request
   was credited exactly nothing. Credit accrues as
   `vram_gb * (duration_seconds / 3600) * rate`, and `duration` is measured with
   `time.time()` (`openai.py:150` and `:498`). `time.time()` on Windows has a
   resolution of roughly 15 ms, so a request that completes faster than one tick
   measures **exactly 0.0 seconds** and the whole product collapses to zero.

The second is the one worth stating plainly: **this is a bug in the credit
ledger's input, not in the test.** `time.time()` is wall-clock, so it is both
coarse *and* non-monotonic — an NTP correction or a DST step during a request can
make a duration negative (currently floored to 0.0 by `max()`, silently crediting
nothing) or wildly too large. `time.perf_counter()` is the monotonic, high-
resolution clock that exists for measuring elapsed time. The Windows leg did not
introduce this defect; it is the only leg whose clock is coarse enough to
*reveal* it. A fast host on any platform is under-credited by the same mechanism.

## Done looks like

- [ ] `.gitattributes` exists and pins `*.sh` to `text eol=lf`, so a Windows
      checkout gets LF and `shellcheck` parses `install.sh` as written.
- [ ] `tests/test_line_endings.py` fails if `.gitattributes` stops pinning `*.sh`
      to LF, or if any tracked `.sh` file contains a CR byte in the index.
- [ ] `openai.py` measures request duration with `time.perf_counter()` at both
      the producer (`started_at`) and the consumer (`duration`) — the only two
      places the value is touched.
- [ ] `packages/scheduler/tests/test_metering_and_accrual.py` gains a test that
      pins a **frozen `time.time()`** and asserts the node is still credited.
      Observed FAILING before the fix and PASSING after — this is what reproduces
      the Windows coarse clock deterministically on Linux.
- [ ] `./scripts/verify.sh` passes locally.
- [ ] CI is green on all nine legs, including the three Windows ones.

## Out of scope

- **ROADMAP 1.5 (a real NAT crossing).** Still partial, still the one functional
  gap in v1, and it cannot be closed from this environment — it needs a second
  physical machine on a genuinely separate network. Explicitly NOT claimed here.
- **Changing the credit *rate* or the accrual formula.** `CREDITS_PER_GB_VRAM_HOUR`
  and the RAM fallback are untouched. This changes only which clock measures the
  duration, so no host is repriced (the D2 concern) — a host that was credited
  correctly before is credited the same amount now.
- **`install.ps1`.** Its own line endings are not what shellcheck reads and it is
  not covered by this change.
- **The `httpx`/`starlette` deprecation warning** visible in the CI logs. Real,
  unrelated, and not a failure.

## Verification

```bash
# the fix for (2), red before and green after
.venv/bin/python -m pytest packages/scheduler/tests/test_metering_and_accrual.py -q

# the ratchet for (1)
.venv/bin/python -m pytest tests/test_line_endings.py -q

# the whole gate, which is what CI runs
./scripts/verify.sh
```

CI itself is verified by reading the run for the pushed commit — a local pass is
not evidence about Windows, which is the entire lesson of this spec.

## Notes / open questions

- `.gitattributes` only takes effect for files as they are **checked out**. It
  does not rewrite what is already in the index, which is why the ratchet checks
  the index bytes (`git ls-files --eol`) rather than the working tree: on Linux
  a working-tree check would pass vacuously.
- `perf_counter()` returns an arbitrary origin, so only *differences* are
  meaningful. Both uses here are differences. `UsageRecord.duration_seconds` is
  already a difference, so nothing downstream changes meaning.
- Worth recording as the recurring pattern: this is the **sixth** time a check
  sat outside the effective definition of "does this pass" — after `tests/`
  (2.9), the website (C6), `scripts/` (C7), `.claude/`, and `install.ps1` (W3).
  Here the check ran and *failed*, and the local gate simply could not see it,
  because one platform's clock and one platform's line endings are not
  reproducible from the platform the gate runs on. `STATUS.md` reported CI as
  `UNVERIFIABLE` (no `gh` CLI) for eight days, which reads like "unknown" and
  was in fact "failing".
