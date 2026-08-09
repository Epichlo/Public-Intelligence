# D4 — Sybil resistance

**Date:** 2026-08-07
**Status:** Decided, and **implemented** on 2026-08-09.

## The question, restated

`POST /nodes` costs nothing and is open to anyone who can reach the Scheduler. One
person can register a thousand nodes and receive dispatch on all of them. ROADMAP
1.2 made *honest* nodes report real hardware, which is worth having, but a malicious
host runs a patched copy — everything a node asserts about itself is unverifiable by
construction.

## Decision

**Registration requires an invite code.** The operator issues codes out of band; a
node presents one at `POST /nodes` and is refused without it.

Design points that matter:

- **Codes are single-use by default**, with an optional use limit for a batch
  invite. A code that registers N nodes is a deliberate choice, not an accident.
- **Codes are stored hashed** (SHA-256), like a password. The store already persists
  per-node credentials; this is the same discipline.
- **Codes can be revoked**, and revoking one does *not* evict nodes already
  registered with it — eviction is a separate operator action, because conflating
  them makes revocation too dangerous to use.
- **The binding is recorded.** Each node records which invite admitted it, so "who
  vouched for this host" is answerable. That is the whole point of the mechanism:
  it moves trust to a human decision and then keeps the receipt.
- **Backward compatibility is a startup choice, not a request-time fallback.** With
  no codes configured the Scheduler runs in open-registration mode and **says so
  loudly at startup**. A silent fallback to open registration would recreate exactly
  the hole this closes.

**Rejected:** proof-of-work (punishes the honest low-power host most), stake
(needs a token, needs law), and hardware attestation (excludes consumer GPUs, which
are the entire supply).

## What this costs, stated plainly

- **Onboarding now has a human in it.** A stranger cannot self-serve a node. For the
  self-hosted product in [D6](D6-is-there-a-network.md) this is nearly free — you
  invite yourself — and for anything larger it is the binding constraint.
- **An invite code is a bearer secret.** Leak one and you have leaked admission. It
  is single-use and revocable to bound that, but it is not a strong identity.
- It does nothing about a *trusted* host that turns malicious. That is
  [D1](D1-execution-integrity.md)'s canary path.

## What changes in the code

- `scheduler/core/invites.py` — issue, verify, redeem, revoke; hashed at rest.
  One subtlety worth recording because the first implementation got it wrong:
  "enforcing" means *any code has ever been issued*, not *a usable code exists now*.
  The latter switches admission back off the moment the last single-use code is
  redeemed — the check disabling itself exactly when it has finished being used.
- `POST /nodes` takes `invite_code`; refuses with 403 when required and absent.
- Persisted in `SchedulerStore` alongside nodes and credentials.
- `scripts/mint_invite.py` — the operator tool that issues them.
- Node side: `NODE_INVITE_CODE` in settings, sent at registration, written by the
  installer prompt.
