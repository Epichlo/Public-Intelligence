# Spec: Scheduler authenticates to nodes (ROADMAP 0.1)

## What this does

The Scheduler proxies inference requests to a node's `/infer` endpoint with no
credentials. That endpoint now requires `X-Network-Auth-Token` and fails closed,
so every real inference request returns 401 — the main path is broken. This makes
the Scheduler remember each node's credential, captured from the registration
request the node already sends, and present it when proxying to that node.

## Done looks like

- [ ] `NodeRegistry` stores a per-node auth token, keyed by `node_id`, and purges
      it on unregister alongside heartbeats, dampeners, and telemetry
- [ ] The token is **never** returned by `get()`, `list_nodes()`, or any API
      response — it lives outside the `Node` model so it cannot leak by
      serialisation
- [ ] `POST /nodes/register` captures the incoming `X-Network-Auth-Token` header
      and stores it against that node
- [ ] Both proxy call sites in `openai.py` (non-streaming `client.post` at ~427
      and streaming `client.stream` at ~487) send the target node's token
- [ ] **`schedule.py`'s proxy resolves the same way.** Scope grew during the first
      verification pass: `schedule.py:95` is a second proxy-to-node call site that
      sent the fleet-wide token, which an installer-provisioned node rejects. Both
      paths now use per-node with fleet-wide fallback. Fixing only `openai.py`
      would have left the feature half-delivered.
- [ ] When no per-node token is known, fall back to `settings.network_auth_token`,
      covered by a test
- [ ] A node re-registering with a rotated token refreshes the stored credential
      even though registration returns 409
- [ ] Regression test observed failing before the fix and passing after, asserting
      the header is present and carries the registering node's token
- [ ] All three suites pass; CI green

## Why per-node rather than a fleet-wide shared token

The existing code implies a shared `NETWORK_AUTH_TOKEN`: `schedule.py:98` sends
`settings.network_auth_token` to any node, and both services declare a
`NETWORK_AUTH_TOKEN` alias. Rejected because:

1. **It cannot be distributed.** `install.sh` is fetched over the public internet.
   A secret baked into it is not a secret. Requiring hosts to obtain one
   out-of-band contradicts one-click install.
2. **It grants lateral movement.** Every host would hold the credential that
   controls every other host, so one compromised contributor machine compromises
   the fleet.
3. **Per-node already exists.** `install.sh` and `install.ps1` generate a random
   64-hex token per install, and `clients/scheduler.py:55` already transmits it
   to the Scheduler on every register call. Only the capture step is missing.

Compromise of one node's token exposes that node alone.

## Out of scope

- **Registration authentication itself.** `/nodes/register` is guarded by
  `verify_auth_token`, which compares the header against the *Scheduler's* token
  and fails open when unset. So today a node's token passes through and is
  accepted. If the Scheduler is ever given a token, node registration breaks
  unless they match. Pre-existing, and a separate fix.
- **Token persistence.** The registry is in-memory (ROADMAP 2.1), so a Scheduler
  restart forgets every token. Nodes do not currently re-register after startup
  (`runtime.py:93` registers once), so recovery needs ROADMAP 1.x/2.1. Not
  addressed here.
- **Token rotation.** Changing a node's token requires re-registration.
- **Node reachability** (ROADMAP 1.1). This fix makes the request *authenticated*;
  it does not make a NAT'd residential node *reachable*. The path stays broken for
  remote hosts until 1.1. This unblocks same-network and containerised topologies.

## Verification

```bash
Scheduler/.venv/bin/python -m pytest Scheduler/tests -q
Node/.venv/bin/python      -m pytest Node/tests      -q
Node/.venv/bin/python      -m pytest tests           -q
grep -n "X-Network-Auth-Token" Scheduler/src/scheduler/api/openai.py   # both call sites
```

Then `VERIFY.md` in full as a separate pass.

## Notes / open questions

- **Re-registration overwrites the stored credential without proving control of
  the node.** Anyone who can reach `/nodes/register` can therefore replace a
  node's token and cause the Scheduler to dispatch with a credential that node
  rejects — a denial of service against that node, not an escalation. The real
  control is authenticating registration itself, which is fail-open today and
  tracked separately (see Out of scope). Refreshing on conflict does not widen
  that exposure: an attacker who can re-register can already register.
- **`set_node_token` / `get_node_token` are deliberately lock-free** while every
  other registry accessor takes `self._lock`. A single dict get or set has no
  await point, so it cannot interleave on the event loop; taking the lock would
  add an await to the hot path of every proxied request and would deadlock if
  called from an already-locked section. Documented at the call site, with the
  condition under which that stops being true.

- The regression was introduced in this session by adding auth to the Node's
  `/infer` without updating the Scheduler's proxy. Nothing caught it: Scheduler
  tests mock `httpx`, Node tests bypass auth via `conftest.py`, and the root E2E
  drives the two apps independently rather than over the wire. ROADMAP 1.5
  (cross-machine integration test) is what would have caught it.
- Storing the token outside the `Node` model is deliberate. Adding a field to a
  Pydantic model that is returned by `GET /nodes` would leak every node's
  credential to any caller.
