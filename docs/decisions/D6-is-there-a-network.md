# D6 — Is there a network at all, and who runs it?

**Date:** 2026-08-07
**Status:** Decided

## The question, restated

`install.sh` writes into every `.env` it generates:

- `NODE_SCHEDULER_URL` pointing at a hosted Scheduler that does not respond
- `NODE_BOOTSTRAP_ROUTERS=["tcp/bootstrap.public-intelligence.net:7447"]`, a name
  that does not resolve

So the installer's happy path produces a node that connects to nothing, and the
failure is silent and slow rather than immediate and clear. Meanwhile the README
and the website describe a network. There is no network.

## Decision

**Ship a self-hosted product. Do not operate a network.**

- **The installer defaults to `localhost`** for both the Scheduler URL and the
  bootstrap router. A fresh install produces a node that works — against a Scheduler
  the same person runs — instead of one that appears to work and does not.
- **Pointing at a remote Scheduler is an explicit act**: `--scheduler-url`, or the
  environment variable, or answering the prompt. Nothing is assumed.
- **No domain is registered and no bootstrap router is operated**, and every
  reference to `public-intelligence.net` as a live service is removed from the
  shipped tree. It survives only in `docs/historical/`, which is already framed as
  describing intentions rather than reality.

## Why this rather than standing up the network

Operating a public network commits to availability, abuse handling, a privacy
posture for other people's prompts, and a bill — all of which are downstream of
[D3](D3-terms-and-liability.md) being answered by a lawyer, which it has not been.
Registering a domain to make the current defaults true would be closing the gap from
the wrong end: it would make the shipped configuration *reachable* without making it
*correct*.

The current state is the worst of both — the cost of claiming a network with none of
the benefit. Either direction beats it. This one is reversible in an afternoon; the
other is not.

## What this costs, stated plainly

- **The demo gets less impressive.** "Run both halves yourself" is a smaller story
  than "join the network". It is the true one.
- **`localhost` defaults are wrong for the multi-machine case**, which is the actual
  goal (ROADMAP 1.5). A host on a second machine must now be told where the
  Scheduler is. That is one flag, and it fails loudly when wrong.
- The claim in [D5](D5-decentralisation-claim.md) narrows with it.

## What changes in the code

- `install.sh` and `install.ps1`: default `NODE_SCHEDULER_URL=http://localhost:8000`
  and `NODE_BOOTSTRAP_ROUTERS=[]`, with a `--scheduler-url` flag and a prompt.
- Empty bootstrap routers means **multicast scouting only** — correct for a LAN,
  and it does not silently dial a dead name.
- `tests/test_installer_defaults.py` fails if a non-resolving hostname re-enters any
  shipped default. This is the durable half: the bug was not that the name was
  wrong, it was that nothing would have noticed.
- README and website say self-hosted, and stop describing a network.

## Reopening this

If a network is ever operated, this record gets a `## Revised` section and the test
above changes. Do not just edit the defaults back.
