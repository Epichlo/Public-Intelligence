# Spec: One command to host a node

## What this does

Turns hosting a node from *clone → install → launch* (three steps, and you have to
know the repo URL and the launch command) into a **single command a person can paste**:

```bash
curl -fsSL https://raw.githubusercontent.com/Epichlo/Public-Intelligence/main/scripts/bootstrap.sh | bash -s -- \
  --scheduler-url https://scheduler.example --fleet-token TOKEN --invite-code CODE
```

That one line fetches the project, installs it, and leaves a **running node daemon**.
It is the on-ramp the "self-host on hardware you own" pitch needs — today there is a
one-command *installer*, but not one-command *hosting*.

Two additive pieces:

1. **`scripts/bootstrap.sh`** — the `curl | bash` target. Clones (or updates) the repo
   and runs `install.sh --start`, forwarding every flag it was given.
2. **`install.sh --start`** — after a *successful* install, launches the node via the
   existing `scripts/launch_host_node.sh start`. Absent the flag, `install.sh` behaves
   exactly as before (installs, prints the start command) — this is backwards compatible.

## Why `--start` is opt-in, and only after success

ROADMAP D-3 is the reason this is careful: `install.ps1` once launched a daemon that
could not import its own package and reported *"launched successfully"*. A single
command that leaves a **broken** node running, and says it succeeded, is worse than one
that stops. So:

- `--start` is explicit. `install.sh` alone does not silently start a daemon.
- It runs only after the install steps complete. `set -e` means a failed install never
  reaches the launch, so the one-liner cannot end in "installed nothing, started nothing,
  said it worked".
- The launcher already verifies the process is alive before reporting success
  (`launch_host_node.sh` checks `is_running` and exits non-zero otherwise), so a daemon
  that dies on startup fails loudly rather than being reported as up.

## Done looks like

- [ ] `scripts/bootstrap.sh` exists, is `chmod +x`, and shellcheck-clean.
- [ ] It clones `${PI_REPO:-the GitHub repo}` at `${PI_BRANCH:-main}` into
      `${PI_DIR:-$HOME/public-intelligence}`, and `git pull`s instead if that dir is
      already a checkout — re-running the one-liner updates rather than fails.
- [ ] It runs `install.sh --start` and **forwards all its own arguments** to it, so
      `curl … | bash -s -- --fleet-token X` reaches the installer.
- [ ] `install.sh --start` launches the node after install; without it, behaviour is
      unchanged (verified by the existing installer checks still passing).
- [ ] `install.sh --start` is a no-op in `--dry-run` beyond printing what it would do.
- [ ] `scripts/verify_install.sh` gains a stage that runs `install.sh --start` for real
      and confirms the node answers `GET /health`, then stops it — proving the single
      command leaves a *live* node, not just files.
- [ ] `scripts/verify_install.sh` gains a stage that runs `bootstrap.sh` against a local
      git origin with `--dry-run`, proving clone + install invocation + argument
      forwarding without touching the network.
- [ ] `bootstrap.sh` is added to the shellcheck list in `scripts/verify.sh`.
- [ ] `tests/test_single_command_host.py` pins the contract (bootstrap forwards to
      `install.sh --start`; `--start` drives `launch_host_node.sh start`).
- [ ] The root `README.md` documents the one-liner.
- [ ] `./scripts/verify.sh` passes.

## Out of scope

- **A hosted install domain** (e.g. `get.public-intelligence.sh`). The one-liner uses the
  raw GitHub URL, which is free and stable. A vanity domain is a DNS/hosting decision,
  and D6 says this project operates no infrastructure.
- **systemd / launchd service units.** `--start` uses the existing nohup-based daemon
  launcher. Surviving a reboot as a managed service is a separate feature.
- **Windows.** `install.ps1` gains no `-Start` here; the one-liner is bash. A PowerShell
  `irm | iex` equivalent is a follow-up, tracked so it is not silently skipped.
- **Auto-detecting the Scheduler.** The one-liner still needs `--scheduler-url` etc.; it
  does not discover a coordinator.

## Verification

```
.venv/bin/python -m pytest tests/test_single_command_host.py -q
./scripts/verify.sh
```

## Notes / open questions

- `curl | bash` executes remote code. That is the accepted norm for installers (Ollama,
  Homebrew, rustup) and the script it runs is the repo's own `install.sh`; the bootstrap
  embeds no secrets and writes none. A cautious operator can read the script at the URL
  first, and the one-liner is documented alongside the clone-then-install path for people
  who prefer it.
- The default clone dir is `$HOME/public-intelligence`. Re-running updates it in place.
