# Spec: The six things a second machine found

On 2026-08-11 a node ran on a second physical machine for the first time and served
a real request over the mesh (ROADMAP 1.5, first clause). Getting there took six
manual workarounds. Each one is a defect, none was visible to 850 passing tests and
a green gate, and every one of them is on the path a first-time host actually walks.

This fixes all six.

## Why none of them were caught

The gate runs `scripts/verify_install.sh`, which executes **`install.sh`** for real
against a throwaway copy. Nothing has ever executed `install.ps1` — it is a
PowerShell script, the runners that could run it are the Windows CI legs, and those
legs run `scripts/verify.sh`, which is bash. So the Windows installer has been
outside "the only definition of does this pass" since it was written. That is the
same silent-partial failure as `tests/` (2.9), the website (C6), `scripts/` (C7) and
`.claude/` — the fifth instance, and the first one found by a user rather than by a
ratchet.

## The six

**D-1 · `install.ps1` installs `packages/node` without `packages/shared`.**
`public-intelligence-node` depends on `public-intelligence-shared`, which is a local
path dependency (C8) with no PyPI presence, so pip resolves nothing and fails.
`install.sh` has installed both, in order, since C8. The Windows copy never did.

**D-2 · `install.ps1` cannot pass an invite code.** No parameter, and nothing written
to `.env`. D4 made invites the admission mechanism and `install.sh` gained
`--invite-code`; the Windows installer was not updated, so a Windows host is refused
by any Scheduler that has issued one.

**D-3 · `install.ps1` reports success over a failed install.** `$ErrorActionPreference
= "Stop"` does not trap a native command's non-zero exit, so after pip failed the
script printed *"Installation Complete! Host Node is Ready"*, launched a daemon that
could not import its own package, printed *"launched successfully"*, and exited 0.

This is the worst of the six and the reason this spec exists. A tool that fails
loudly costs you an afternoon. A tool that **claims success while failing** costs you
the afternoon plus the time spent looking in the wrong place, and it trains you to
distrust every other success message it prints. It is the same defect class as the
orchestrator that returned `verification_passed=True` for a stub (2.10) and the
batch endpoint that fabricated completions (C9) — this repo has now shipped it three
times, in three languages.

**D-4 · `install.ps1` prints a run command that cannot find the `.env` it just
wrote.** Settings resolve `env_file=".env"` relative to the *working directory*
(`configuration.py:195`). The backgrounded daemon is launched with
`-WorkingDirectory $NodeDir` and is fine; the command printed for the user to copy
has no `cd`, so following the installer's own instructions produces a node running
entirely on defaults — wrong id, no credential, and `scheduler_url` pointing at the
host's own localhost. The observed symptom was `All connection attempts failed`
against a Scheduler that was up the whole time.

**D-5 · No installer can supply the credential registration requires.**
`/nodes/register` carries `Depends(verify_auth_token)` (`nodes.py:58`), which compares
`X-Network-Auth-Token` against the Scheduler's fleet token. Both installers instead
*generate a random per-install token*, which by construction never matches. A host
installed by the documented path cannot register against any Scheduler that sets one.

This is the one defect here that is not simply an omission, and it is recorded rather
than papered over: **one header carries two meanings.** `register_node` reads
`x_network_auth_token` to store as the node's own credential, and `verify_auth_token`
has already required that same header to equal the fleet secret. So the "per-node
credential" that 2.7 keys mesh envelopes on can only ever *be* the fleet secret
whenever one is configured. The per-node isolation 2.7 claims does not survive a
Scheduler with a fleet token. Splitting those two meanings into two headers is a
protocol change with a migration, so it gets a decision record and not a patch in
this spec — see "Out of scope".

**D-6 · A CPU-only host can never accrue credit.**
`earned = vram_gb * hours * CREDITS_PER_GB_VRAM_HOUR` (`credit_ledger.py:114`), and a
CPU-only node reports `vram_total_gb: 0.0`. ROADMAP 1.2 deliberately made CPU-only
nodes representable and dispatchable; 3.3 measures contribution purely in VRAM-hours.
Those two decisions contradict each other. The machine that closed 1.5 served a real
request and was recorded as having contributed **exactly nothing** — `earned=0.00,
new_balance=0.00` — which is the "never render uncertainty as zero" defect wearing
different clothes: real work rendered as no work.

## Design decisions, and why

**The Windows installer gets a smoke test, not a promise to be careful.** D-1 through
D-4 are all "someone updated `install.sh` and forgot the other one". Fixing the four
without closing the gap that produced them would leave the fifth to be found by the
next user. `tests/test_installer_parity.py` asserts the two installers agree on the
things a host cannot install without — invite code, auth token, scheduler URL,
bootstrap router, and installing `shared` before `node` — by reading both files. It
is a text-level check because the gate cannot execute PowerShell on Linux, and it
says so rather than implying more.

**`$LASTEXITCODE` is checked after every native call, and the script stops.** Not
"warns". `install.sh` has had `set -e` since it was written; the PowerShell copy gets
the equivalent.

**The daemon is not launched when the install failed.** Launching a process that
cannot import its package, then reporting it as running, is what made D-3 expensive.

**CPU contribution is credited on RAM-hours, and the arbitrariness is stated.**
A CPU-only host's scarce resource is memory, which `Node.ram_total_gb` already
carries as a measured figure. `CREDITS_PER_GB_RAM_HOUR` is set to one tenth of the
VRAM rate. **That ratio is a guess**, in the same sense the watcher's thresholds are
guesses: nobody has measured what a GPU-hour is worth relative to a CPU-hour on this
network, because there is no network. It is a named constant with a comment saying so,
not a derived figure — and it is vastly better than the current answer, which is that
the work never happened.

## Done looks like

- [ ] `install.ps1` accepts `-InviteCode` and `-NetworkAuthToken`, and writes
      `NODE_INVITE_CODE` / `NODE_NETWORK_AUTH_TOKEN` to `.env`.
- [ ] `install.ps1` installs `packages/shared` before `packages/node`.
- [ ] `install.ps1` checks `$LASTEXITCODE` after every native command and exits
      non-zero on failure, printing no success banner.
- [ ] `install.ps1` does not launch the daemon when the install failed.
- [ ] The command `install.ps1` prints for manual use `cd`s to the node directory
      first, so it finds `.env`.
- [ ] `install.sh` accepts `--network-auth-token` and writes it, so a POSIX host can
      register against a Scheduler with a fleet token without hand-editing `.env`.
- [ ] `tests/test_installer_parity.py` fails if either installer loses any of:
      invite code, network auth token, scheduler URL, bootstrap router, or the
      shared-before-node ordering.
- [ ] `tests/test_installer_parity.py` fails if `install.ps1` regains a success
      banner that is not guarded by an exit-code check.
- [ ] A CPU-only node accrues non-zero credit for a successful request, covered by a
      test that fails against the current VRAM-only formula.
- [ ] A GPU node's credit is unchanged, so this is additive rather than a repricing.
- [ ] `./scripts/verify.sh` passes.

## Out of scope

- **Splitting the two meanings of `X-Network-Auth-Token` (D-5's root cause).** The
  fix here lets an installer *supply* the credential; it does not separate "fleet
  admission" from "this node's mesh key". That needs a decision record, a header, and
  a migration for already-registered nodes. Recorded as a ROADMAP item, not silently
  left.
- **Executing `install.ps1` in CI.** The parity test reads both files; it does not run
  the PowerShell one. Running it needs a Windows runner step, and `ci.yml` may not
  grow its own check list (`test_source_parity.py`). Doing it properly means teaching
  `scripts/verify.sh` to invoke PowerShell when present, which is its own change.
- **Repricing credits.** D2 made these an accounting unit with no redemption. The
  RAM rate makes CPU work visible; it does not claim to value it correctly.
- ~~**The `NODE_ID` env var being ignored.**~~ **Fixed after all, because the audit
  showed it was a release blocker rather than a wart.** It was listed here as out of
  scope on the grounds that it is cosmetic. It is not: the registry keys on
  `node_id` and so does the mesh queryable `public-intelligence/net/{node_id}/infer`,
  so two hosts would occupy one registry slot and answer the same key. A network of
  one works; a network is the point. Now ROADMAP W8, with W9 for the ratchet that
  was supposed to catch it and could not.

## Verification

```
.venv/bin/python -m pytest tests/test_installer_parity.py -q
.venv/bin/python -m pytest packages/scheduler/tests/test_credit_ledger.py -q
./scripts/verify.sh
```

## Notes / open questions

- **Five of the six are Windows-only, and that is the finding.** Not "Windows is
  awkward" — that an entire installer sat outside the gate for its whole life and
  nobody noticed until a human ran it.
- The RAM-hours rate is unmeasured. If a real fleet ever exists, it should be derived
  rather than kept.
