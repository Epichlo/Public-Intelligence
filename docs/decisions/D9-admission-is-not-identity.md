# D9 — Admission is not identity

**Decided 2026-08-11.** Split `X-Network-Auth-Token` into two headers, because it is
currently answering two different questions with one value.

## The question

`POST /nodes/register` reads one header and uses it for two unrelated purposes:

1. **Admission.** `Depends(verify_auth_token)` compares it against the Scheduler's
   `network_auth_token` — "does this caller know the fleet secret?"
2. **Identity.** `register_node` stores it via `set_node_token` as *that node's own*
   credential, which the Scheduler later uses to verify the node's mesh envelopes
   (`zenoh_router.py:215`) and to authenticate to the node's control API when
   dispatching (`node_dispatch.py:59`).

Those cannot both hold. If the value must equal the fleet secret to get past (1),
then the "per-node credential" stored by (2) **is** the fleet secret, for every node.

## Why this matters more than it looks

ROADMAP 2.7 closed a real hole: anyone who could reach the bootstrap router could
forge telemetry, heartbeats, and liveliness for any node, and evict any host. Its fix
was to key every state-changing mesh message on *that node's own* credential —
explicitly so that a fleet-wide secret could not be used to impersonate another node.
The commit message for it says the insider case is "closing the insider case a
fleet-wide secret never could."

It does not close it. The moment an operator sets a fleet token — which they must, or
`/nodes`, `/metrics` and `/v1/models` serve anyone — every node's key becomes that one
shared value, and any host can forge messages as any other. 2.7's central property
silently does not hold in the configuration everyone runs.

Nothing warns about this. That is the part that decides it: a security property that
is present in the tests and absent in deployment is worse than one that was never
claimed, because it stops anyone looking.

## The decision

**Two headers, two meanings.**

| Header | Means | Checked by |
|---|---|---|
| `X-Network-Auth-Token` | the fleet's admission secret | `verify_auth_token` |
| `X-Node-Credential` | *this* node's own secret | stored, never compared |

The node sends both at registration. The Scheduler stores `X-Node-Credential` as the
node's key; `X-Network-Auth-Token` is only ever compared, never retained.

On the node, `NODE_NETWORK_AUTH_TOKEN` returns to its original single meaning — the
per-install secret that guards the node's own control API and signs its mesh
envelopes — and a new `NODE_FLEET_TOKEN` carries the operator's admission secret.

## What was rejected, and why

**Scheduler issues the key at registration** (node presents nothing, receives a
credential in the response). Cleaner in principle, and wrong here: the node needs its
key *before* registering, because its control API fails closed and the installer must
write something. It would also mean the credential crosses the wire in a response
body rather than a header the node already holds.

**Public-key identity** (node proves possession, no shared secret). The right long-term
answer and far too large for this: it changes envelope sealing, the store schema, and
the installer. D9 is the smallest change that makes 2.7's claim true; it is not the
last word on node identity.

**Renaming rather than adding.** Reusing `X-Network-Auth-Token` for the per-node value
and adding a new header for admission would break every registered node at once. The
new header is the *added* one precisely so absence is backwards compatible.

## The cost, stated

- **Two secrets in `.env` instead of one.** More to explain, and an operator who sets
  only one still gets a working node — by design, see below.
- **The fallback keeps the old hole open for old nodes.** A node that sends no
  `X-Node-Credential` still has its admission token stored, exactly as before. That is
  deliberate: refusing them would strand every currently-registered host. The
  weakness persists for un-upgraded nodes and is not silently repaired.
- **This does not make the mesh secure against a malicious operator**, who holds every
  node's credential by construction. It closes host-to-host impersonation, not
  operator-to-host.

## What changes in the code

- `register_node` accepts `X-Node-Credential` and stores it in preference to
  `X-Network-Auth-Token`, falling back when absent.
- The node's `SchedulerClient` sends both headers.
- `Settings` gains `fleet_token`, and `network_auth_token` is documented as the
  node's own secret again.
- Both installers gain a flag for the fleet token and keep generating the per-node one.
- `tests/test_admission_is_not_identity.py` pins that two nodes registering against a
  fleet-token Scheduler end up with *different* stored credentials — the property that
  is false today.
