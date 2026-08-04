# Spec: Node reachability (ROADMAP 1.1)

## What this does

Today the Scheduler reaches a node by dialling `http://<ip_address>:8080/infer`. Every
node installed by `install.sh` registers `ip_address = 127.0.0.1`, so the Scheduler dials
itself, and a node on a home connection has no inbound port to dial anyway. No remote node
has ever served a request.

This routes inference over the Zenoh session the node **already dials out and holds** —
the same session it uses for heartbeats, liveliness, and telemetry. The node declares a
Zenoh *queryable*; the Scheduler *queries* it. Replies travel back over the node's existing
outbound connection, so no inbound port, no port forwarding, no NAT traversal, and no new
relay service to operate. `ip_address` stops being load-bearing for dispatch.

The HTTP path stays as a fallback for same-host and containerised deployments.

## Why a Zenoh queryable rather than a relay

The alternatives considered:

1. **HTTP relay service.** The Scheduler posts to a relay; nodes long-poll or hold a
   websocket to it. Rejected: it is a new service to deploy, scale, and secure, and it
   reimplements what the mesh already does. The node *already* holds an outbound session
   that survives NAT; nothing is gained by building a second one over HTTP.
2. **NAT traversal / port forwarding.** Rejected: it cannot be made to work unattended on
   arbitrary residential routers, and "open a port on your router" is not one-click install.
3. **Zenoh pub/sub with a request topic and a reply topic.** Workable, but correlation,
   timeouts, and cleanup all have to be hand-rolled. The query/reply primitive provides
   exactly that, and supports **multiple replies to one query**, which is what token
   streaming needs.

So: queryable. It is the primitive the problem asks for, over transport that already works
in this repo (`Scheduler/tests/test_zenoh_integration.py` drives a real router on TCP
loopback and passes).

## The wire contract

Key expression: `public-intelligence/net/{node_id}/infer`

**Request** (JSON, in the query payload):

```json
{
  "node_id": "node-abc",
  "model": "llama3",
  "prompt": "...",
  "stream": false,
  "nonce": "<32 hex>",
  "timestamp": 1775000000.0,
  "signature": "<hex hmac-sha256>"
}
```

**Replies** (JSON, one or more, on the queryable's own key expression):

- non-streaming: `{"ok": true, "model": "llama3", "response": "..."}`
- streaming: `{"ok": true, "i": 0, "chunk": "Hel"}` … then `{"ok": true, "done": true}`
- error: `{"ok": false, "status": 401, "error": "..."}`

The Scheduler queries with `consolidation=ConsolidationMode.NONE`. This is not optional,
and it was measured rather than assumed: changing it to `LATEST` and running
`tests/test_mesh_inference_e2e.py` against a real router fails **4 of 8** tests. The
streaming test fails as predicted — every chunk replies on the same key expression, and a
consolidating router holds back or drops samples sharing a key, so tokens vanish. The
surprise is the other three: the error-reply paths (unsigned request, unconfigured node,
missing model) fail too, timing out as though the node never answered. So consolidation
affects single-reply correctness as well, not only streaming, and the failure it produces
looks exactly like an unreachable node — which would have sent every request down the HTTP
fallback for reasons no log would explain.

### Authentication: HMAC proof, not the token itself

`/infer` over HTTP sends `X-Network-Auth-Token` — the node's actual credential — and the
Node compares it with `hmac.compare_digest` (`Node/src/node/api/auth.py`). Copying that
onto the mesh would put the credential in a payload that crosses a shared router in
plaintext under the default Zenoh config, readable by the router operator and by anyone who
can see the link.

So the mesh request carries a **proof of possession** instead. Both sides compute

```
body_digest = SHA256(f"{model}\0{prompt}\0{'1' if stream else '0'}")
signature   = HMAC-SHA256(token, f"{node_id}\n{nonce}\n{timestamp:.6f}\n{body_digest}")
```

and the Node compares with `hmac.compare_digest`. Two details that are load-bearing rather
than incidental: the timestamp is signed at **fixed precision**, so the signature does not
depend on a float's repr surviving a JSON round-trip; and `stream` is rendered `1`/`0`
rather than Python's `True`/`False`, so the contract does not assume the implementation
language. `\0` separates the digest fields because it cannot occur in any of them, so no
combination of model and prompt can be re-split into a different request with the same
digest.

The token never crosses the wire. The
signature is bound to the request body, so a captured request cannot be edited into a
different prompt. This follows the HMAC pattern already used for telemetry envelopes in
`scheduler/core/zenoh_router.py:_process_telemetry`.

Fail-closed, matching `verify_node_auth`: a node with no `network_auth_token` configured
serves nothing over the mesh either.

**Replay:** requests older than ±30s are rejected (same window as telemetry), and each
`nonce` is accepted once — a bounded LRU of seen nonces, sized to comfortably outlive the
window. Telemetry does not do the nonce half, so a captured telemetry envelope is still
replayable for 30s; that is a pre-existing gap in a different envelope, not fixed here.

### The envelope module is duplicated, deliberately, and guarded

The request/reply contract has to be identical in both packages, and there is no shared
installable package to hold it (`src/shared/` is a third, unimported copy of the artifact
store, not a real dependency). So `mesh_protocol.py` lands **byte-identical** in
`Node/src/node/core/` and `Scheduler/src/scheduler/core/` — joining the four modules
CLAUDE.md already warns about.

Unlike those four, this pair is guarded: a test in the **root** suite (the only interpreter
where both packages import) asserts the two files are byte-identical **and** round-trips a
request signed by one against the other. Silent drift of the kind that hit
`autonomous_orchestrator.py` fails a test here.

### Which transport a request takes

The Scheduler prefers the mesh when it has **observed that node on the mesh** — a Zenoh
heartbeat, a telemetry envelope, or a liveliness token PUT. That is an observed signal, not
a self-advertisement: a node cannot claim mesh reachability it does not have.

It is still not proof that the *queryable* was declared, so the mesh attempt falls back:

| Outcome | Behaviour |
|---|---|
| No reply within the first-reply deadline | fall back to HTTP |
| No queryable matched at all | fall back to HTTP, immediately — the reply iterator ends rather than waiting out the deadline |
| Transport error | fall back to HTTP |
| `{"ok": false, ...}` from the node | **no** fallback — the node answered; surface it |
| Streaming, failure before the first chunk | fall back to HTTP |
| Streaming, failure after the first chunk | propagate the error; bytes are already sent |
| Streaming ends with no `done` terminator | error, not a clean end — a truncated completion must not look complete |

In code these are two exception types, not one: `MeshUnavailableError` (fall back) and
`MeshNodeError` (surface). Collapsing them would mean a node's 404 for an unpulled model
came back as a generic 502 after a pointless retry.

## Done looks like

- [x] `mesh_protocol.py` exists in both packages, byte-identical, with
      `build_request` / `verify_request` / reply encoders, and a root-suite test that
      fails if the two copies diverge or stop interoperating
      — `tests/test_mesh_protocol_parity.py`
- [x] `verify_request` rejects: no token configured, wrong signature, a body edited after
      signing, a timestamp outside ±30s, and a replayed nonce — one test each
      — `Node/tests/test_mesh_protocol.py`, 19 tests
- [x] The Node declares a queryable on `public-intelligence/net/{node_id}/infer` when its
      Zenoh session is up, and undeclares it on `Runtime.stop()`
      — `Node/tests/test_runtime_mesh_wiring.py`
- [x] A mesh request with a valid signature returns Ollama's output; streaming yields one
      reply per chunk then a `done` reply — `Node/tests/test_mesh_inference_server.py`
- [x] `NodeRegistry` tracks mesh reachability, and purges it on unregister alongside
      heartbeats, dampeners, telemetry, and tokens
      — `Scheduler/tests/test_registry/test_mesh_reachability.py`
- [x] `ZenohRouter` marks a node mesh-reachable on Zenoh heartbeat, telemetry, and
      liveliness PUT — `Scheduler/tests/test_zenoh_mesh_reachability.py`
- [x] `/v1/chat/completions` (streaming and non-streaming) and `/infer` all route over the
      mesh for a mesh-reachable node — asserted by tests that would fail if the code dialled
      HTTP instead — `Scheduler/tests/test_mesh_dispatch_routing.py`, which asserts
      `httpx` was never awaited
- [x] Each falls back to HTTP when the mesh attempt yields nothing, and does **not** fall
      back when the node returns an error — same file
- [x] An end-to-end test over a **real** Zenoh router on TCP loopback: real node-side
      queryable, real Scheduler-side query, no mocked session — non-streaming and streaming
      — `tests/test_mesh_inference_e2e.py`, 8 tests
- [x] All three suites pass; ruff clean on both packages

## Out of scope

- **Deleting the HTTP path.** It stays as the fallback and is what
  `docker-compose.test.yml` exercises. Removing it is not required to make remote nodes
  reachable.
- **Fixing `ip_address = 127.0.0.1`** (`runtime.py:252`, `install.sh:277`). Still wrong,
  still misleading in `GET /nodes`. It stops being load-bearing for dispatch, which is why
  it is not fixed here; it belongs with real hardware advertisement (ROADMAP 1.2).
- **A test across two real machines.** Everything here runs a real router in one process on
  loopback. Two hosts, two NATs, real RTT is ROADMAP 1.5.
- **TLS on Zenoh links.** The HMAC scheme means the credential is not exposed, but prompts
  and completions still cross the router in plaintext — as they do today over `http://`.
  Not a regression; needs its own item.
- **Persisting mesh reachability.** In-memory like the rest of the registry (ROADMAP 2.1).
  A Scheduler restart re-learns it from the next heartbeat.
- **Real hardware advertisement and heartbeat metrics** (1.2, 1.3) — matchmaking still
  filters on the hardcoded `vram_total_gb: 16.0`. A node reached over the mesh is selected
  on the same fiction as before.
- **Batch and split-inference paths.** `/v1/batch` and the split-stage tensor topics are
  untouched.

## Verification

```bash
Scheduler/.venv/bin/python -m pytest Scheduler/tests -q
Node/.venv/bin/python      -m pytest Node/tests      -q
Node/.venv/bin/python      -m pytest tests           -q
Scheduler/.venv/bin/python -m ruff check Scheduler/src
Node/.venv/bin/python      -m ruff check Node/src
diff Node/src/node/core/mesh_protocol.py Scheduler/src/scheduler/core/mesh_protocol.py
```

Then `VERIFY.md` in full as a separate pass.

## Notes / open questions

- **Zenoh finalises a query when the `Query` object is dropped.** The queryable callback
  runs on a Zenoh thread and inference is async, so the callback hands the `Query` to a
  coroutine via `run_coroutine_threadsafe` and returns immediately. The coroutine holding a
  reference is what keeps the query open. If that reference were dropped early, replies
  would be discarded. The real-router test is what pins this behaviour rather than an
  assumption about it.
- **Reply ordering.** Chunks carry an index `i`. Zenoh does not contractually guarantee
  reply ordering, so the client logs a warning on a non-monotonic index rather than
  pretending it cannot happen. It does not reorder — a reordering buffer needs a real
  failure to design against, and no observed one exists yet.
- **Query timeout vs. generation time.** The Zenoh query timeout covers the whole
  request, so a long generation needs a generous value (default 120s) while the *fallback*
  decision needs a short one. These are separate settings:
  `mesh_inference_timeout_seconds` and `mesh_inference_first_reply_timeout_seconds`.
- **A node marked mesh-reachable that never declared a queryable pays a first-reply
  timeout per request** before falling back. Bounded by the short deadline, and the mark is
  only set by observed mesh traffic. If this shows up in practice the fix is to remember
  the failure per node; not built, because there is no evidence yet that it happens.
- **This does not change who can query a node.** Anyone able to reach the mesh can send a
  query to any node's key expression, but without that node's token the signature check
  rejects it. The Scheduler is the only party holding node tokens (captured at
  registration, ROADMAP 0.1).
