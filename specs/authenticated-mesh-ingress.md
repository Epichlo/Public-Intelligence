# Spec: Authenticated mesh ingress (ROADMAP 2.7, absorbing 2.5)

## What this does

The Scheduler accepts three kinds of input from the Zenoh mesh and authenticates
none of them usefully. After this, every message that changes registry state is
signed with a key only that node has, and the one signal that cannot be signed
stops changing state at all.

## What actually breaks today

Zenoh links are plaintext and `bootstrap.public-intelligence.net:7447` is public,
so "can reach the mesh" is not a privilege. Three ingress paths, in increasing
severity:

**1. Telemetry — signed with a key published in this repo.**
`os.environ.get("TELEMETRY_SECRET_KEY", "<constant in this file>")` in *both*
services. Forged telemetry writes `registry._telemetry[node_id]`, which
`matchmaker.score_nodes` reads for `reliability`, `queue_depth` and `cpu` — so
`reliability_score: 999` wins every dispatch — and `filter_nodes` reads for
`backend_type`.

**2. Heartbeats — no authentication at all.** `_process_heartbeat` parses plain
JSON off `net/*/heartbeat` and writes `registry._heartbeats[node_id]`, which
`filter_nodes` compares against a task's `min_vram_gb`. The node publishes it
unsigned. **This is why ROADMAP 2.2 as written ("rotate the key") was superseded:**
an attacker who loses telemetry forgery just forges a heartbeat and reaches
equivalent state one topic over.

**3. Liveliness — unauthenticated, and it deletes nodes.** `_on_liveliness` takes
`node_id` from `parts[3]` of a key expression *the publisher chose*, and a DELETE
calls `_process_deathrattle` → `registry.unregister_node(node_id)`. Declaring a
liveliness token for someone else's node id and dropping it **evicts that host from
the network**. This is the most severe of the three and was not in 2.2's framing at
all.

### Why 2.5 gets absorbed

ROADMAP 2.5 says "Deathrattle and stale-eviction now apply correctly". **The
stale-eviction half does not exist.** Verified: no periodic sweep, no `last_seen`
check on nodes anywhere in `packages/scheduler/src` — the only hits are
`consensus.py`, which tracks peer *Schedulers*, and a comment in
`node_registry.py:376` that inherited the claim from that roadmap line. A node
leaves the registry only by a graceful `DELETE /nodes/{id}` or by the
unauthenticated deathrattle.

So removing the deathrattle's write without building a time-based replacement
would trade an eviction hole for a leak: dead hosts advertised forever. The
minimum of 2.5 — a sweep that removes nodes whose last authenticated heartbeat is
too old — is therefore part of this change, not a follow-up. 2.5's roadmap line is
corrected rather than left asserting something untrue.

## Design decisions, and why

**Keys come from each node's own credential, not a fleet-wide secret.**
`NODE_NETWORK_AUTH_TOKEN` is already generated per install by `install.sh`,
presented at registration, and stored by the Scheduler outside the `Node` model. A
shared symmetric key could only ever stop outsiders — every host holds it, so any
participant can forge for any other. Per-node keys close that too, need no operator
action, and follow the pattern 1.1 already established for mesh inference.

**A derived key, never the raw token.** `sha256(token || context)` with a distinct
context per purpose, so a telemetry key cannot open a heartbeat and neither key is
the credential the node presents over HTTP. The existing code already did domain
separation this way (`sha256(secret + b"-encryption")`); this keeps the idiom and
widens the context to include the protocol and the purpose.

**One AEAD, not an AEAD plus an HMAC.** The first cut of this ported the previous
envelope shape: AES-256-GCM *and* a separate SHA-256 HMAC over the ciphertext.
Mutation testing showed the HMAC was doing no work -- deleting its verification
changed no test outcome, because AES-GCM is an AEAD and its own tag rejected the
same envelopes. Two mechanisms where only one is load-bearing is worse than one,
because a reader cannot tell which to trust. The HMAC is gone; `node_id` and
`purpose` are passed as GCM **associated data** instead, so the binding is
enforced by the cipher rather than beside it.

**What actually stops a cross-topic replay is the key lookup, and the spec says so
rather than claiming credit for the binding.** The Scheduler derives the key from
the node that OWNS THE TOPIC, so an envelope minted with one node's credential
cannot open under another's -- full stop. The `node_id` in the associated data and
the explicit field check are defence in depth: removing BOTH still leaves the
replay test green. They earn their place by keeping the property true if keys were
ever shared again, not by doing the work today. Recorded because an
untested-because-redundant control is exactly the kind of thing that later gets
described as the reason something is safe.

**An unauthenticated signal may accelerate a check, never perform a write.**
Liveliness cannot be signed — a token carries no payload — so it stops mutating the
registry. A DELETE now marks the node *suspect*, which makes the sweep look at it
immediately instead of at the next interval; if an authenticated heartbeat has
arrived recently, nothing happens. This keeps the fast deathrattle behaviour for
the honest case and makes the hostile case a no-op.

**Eviction becomes time-based and authenticated.** A node is removed when its last
*verified* heartbeat is older than `node_stale_after_seconds` (default 90 — three
missed heartbeats at the node's 30s default). This is the mechanism 2.5 claimed
existed.

**Messages from an unregistered or token-less node are dropped, not queued.** The
Scheduler cannot verify what it has no key for. After 1.6 a node that is not
registered re-registers on a jittered backoff, so the window is bounded and
self-healing; accepting unverifiable data to cover it would reopen the hole.

**Two byte-identical copies, not a new shared package.** This reverses what I
recommended when scoping: I argued `packages/shared/` should be the forcing
function. ROADMAP 2.8 changed the facts — `scripts/verify_install.sh` now really
runs `pip install -e packages/node`, so a `pi-shared` dependency that pip cannot
resolve from a path would break a property that is now tested and load-bearing.
The repo already has the right pattern for exactly this: `mesh_protocol.py` is
duplicated, held **byte-identical** by `tests/test_mesh_protocol_parity.py`, and
round-tripped through both copies with real data. The new module joins that test at
a drift budget of 0, which is stronger than a shared module would need to be.
`packages/shared/` stays the recorded end state.

**`TELEMETRY_SECRET_KEY` is removed entirely**, not defaulted to empty — from both
services, `install.sh`, `install.ps1` and `docker-compose.test.yml`. A setting that
no longer does anything is worse than no setting: an operator who sets it would
believe they had configured something.

## Done looks like

- [x] Forged telemetry for a registered node, signed with the old published
      constant, is rejected and does not reach `registry._telemetry`. Test.
- [x] Telemetry signed with the node's own token is accepted. Test.
- [x] A heartbeat published as plain JSON is rejected. Test.
- [x] A heartbeat signed with the node's own token is accepted and updates
      `registry._heartbeats`. Test.
- [x] A valid envelope replayed onto a *different* node's topic is rejected. Test.
- [x] Telemetry/heartbeat for an unregistered node, or one with no stored token,
      is dropped without raising. Test.
- [x] A liveliness DELETE for a node with a recent verified heartbeat does **not**
      unregister it. Test — this is the eviction hole.
- [x] A node whose last verified heartbeat is older than
      `node_stale_after_seconds` is removed by the sweep. Test.
- [x] The sweep starts with the router and is cancelled on shutdown. Test.
- [x] `TELEMETRY_SECRET_KEY` appears nowhere in `packages/`, `install.sh`,
      `install.ps1` or `docker-compose.test.yml`. Covered by a test.
- [x] The two `mesh_auth.py` copies are byte-identical and round-trip a real
      envelope through each other. Covered by the existing parity test, budget 0.
- [x] Purpose separation is enforced: a telemetry envelope does not open as a
      heartbeat. Verified by mutation -- removing purpose from BOTH the key
      derivation and the associated data turns the test red.
- [x] `./scripts/verify.sh` passes.

## Out of scope

- **Encrypting the Zenoh transport itself.** Envelopes stay AES-GCM inside
  plaintext links. Payload confidentiality and authenticity are what change here.
- **Rotating a node's token without re-registering.** A rotated token reaches the
  Scheduler at the next registration, which 1.6's retry loop and 2.1's persistence
  already handle. No online rekey.
- **Replay within the freshness window.** Telemetry keeps its existing 30s
  timestamp check; an attacker who captures an envelope can still replay it inside
  that window. A nonce cache would close it and is not built here.
- **Authenticating mesh *inference*.** Already done by 1.1, unchanged.
- **`packages/shared/`.** Still the right end state, still not built. Reasoning above.
- **The rest of 2.5.** `_process_deathrattle` logging success unconditionally is
  moot once it stops unregistering; what remains of 2.5 is whether eviction is
  *observable*, which this does not address.

## Verification

```
./scripts/verify.sh
.venv/bin/python -m pytest packages/scheduler/tests/test_mesh_ingress_auth.py -q
.venv/bin/python -m pytest tests/test_mesh_protocol_parity.py -q
grep -rn "TELEMETRY_SECRET_KEY" packages install.sh install.ps1 docker-compose.test.yml
```

## Notes / open questions

- Duplicate-module check: `mesh_auth.py` is a new sixth duplicated pair, added
  deliberately and at budget 0. `telemetry.py`'s `derive_keys`/`encrypt_payload`
  are replaced by it rather than left beside it.
- Open: the telemetry handler's node-id fallback reads `parts[4]` of
  `public-intelligence/net/nodes/{id}/telemetry`, which is the literal string
  `"telemetry"`, not the id. Harmless today because the payload always carries
  `node_id`, and moot after this change since the id must come from the topic to
  pick a key. Removed rather than fixed in place.
- The 90s default assumes the node's 30s heartbeat interval. Both are settings and
  nothing enforces the relationship; a host who widens their interval past the
  Scheduler's window would be evicted repeatedly. Worth a startup warning later.
