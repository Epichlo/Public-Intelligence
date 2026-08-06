# ROADMAP — v1

Status: **draft for review.** Nothing here is being built yet.

This supersedes `docs/ROADMAP.md`, which describes phases 4.6–4.9 as "Realized"
based on code that does not do what the labels claim. Where the two disagree,
this file is correct.

---

## What v1 is

> **A decentralised inference marketplace.** A person with a spare GPU runs one
> command and their machine starts serving requests. A developer points an
> OpenAI-compatible client at one URL and gets completions back, served by
> somebody's donated hardware. The host can see what their machine did and what
> it earned.

Each request is served **by a single node**, running a model that fits on that
node's own hardware. The network's job is matchmaking, delivery, and accounting —
not splitting a model across machines.

## What v1 is not

**No layer sharding, no split-inference, no FP8 compression, no speculative
decoding, no KV-cache checkpointing.** These are cut from v1 deliberately.

### Why cutting them is the right call

I considered whether the distributed-inference layer *is* the product, such that
cutting it means this isn't v1. I concluded it is not, for four reasons:

1. **The value loop closes without it.** Host donates idle GPU → requester gets
   inference → host earns credit. Every part of that works with one model on one
   machine. Sharding lets you run models *larger than any single node*, which
   expands the catalogue; it is not what makes the exchange work.

2. **What exists today is a simulation, not an implementation.** `LocalBoundaryEngine`
   is a 155-word vocabulary and two seeded `random.gauss` matrices; "speculative
   candidates" are `(prev * 7 + 13) % vocab_size`. Real sharding needs real weights,
   real tensor ops, and a real runtime. The distance from here to there is a
   rewrite, not a fix. Betting v1 on it means v1 does not ship.

3. **The hard part is unsolved by anyone at this scale.** Splitting a model across
   residential links at 50–150ms RTT is an open research problem. Petals does it
   with a lot of tolerance for latency. Making it the gate on v1 converts a
   product launch into a research project.

4. **The unglamorous blockers are what's actually stopping users.** No remote node
   can receive a request at all today (see below). That is worth more than any
   amount of FP8.

### What cutting them costs — stated plainly

The pitch narrows. "Frontier models sharded across homes" is not v1. **"Open models
that fit on one consumer GPU, served over a network of donated machines, behind an
OpenAI-compatible API"** is. That means roughly 7B–70B class models depending on the
host, not 400B+.

That is a real product — the economics of idle consumer hardware stand on their own —
but it is a smaller claim than the current docs make, and the docs will need to stop
making the larger one.

Sharding becomes **v2**, attempted only once v1 has real hosts and real traffic to
justify it.

---

## The honest starting position

Verified in this session, not inferred:

**Working:** Node service and Ollama-backed `/infer`; node registration and
heartbeat; Zenoh telemetry mesh (AEAD encrypted); Scheduler registry, matchmaker,
and OpenAI-shaped gateway; RS256 JWT auth on the gateway; authenticated node
control API; POSIX and Windows installers; dashboard and playground UI; CI green
on six legs.

**The blocker that defined this roadmap:** every node installed by `install.sh` registers
`ip_address = 127.0.0.1` (`Node/src/node/runtime.py:252`, `install.sh:277`). The
Scheduler built `http://127.0.0.1:8080/infer` and dialled itself. **No remote node
had ever served a request.** Every green test exercised one process talking to itself.

That single fact is why v1 is defined around delivery and reachability rather than
around inference performance.

**Where that stands now (1.1 done).** Inference no longer depends on dialling
`ip_address`: it is routed over the Zenoh session the node dials out and holds, and the
mesh path is exercised against a real Zenoh router rather than a mock
(`tests/test_mesh_inference_e2e.py`). Stated precisely, because the distinction matters:
that router runs in one process on TCP loopback. **A node on a genuinely separate machine,
behind a real NAT, still has not served a request.** The transport that should make it
possible is built and tested; the claim that it works on real hardware is not yet earned,
and 1.5 is what would earn it.

`ip_address` is still `127.0.0.1` — it stopped being load-bearing for dispatch rather than
becoming correct. **1.2 addressed the misleading part rather than the value:** `GET /nodes`
now returns a `reachability` field (`mesh` / `http`) derived from the registry's own mesh
observations, so a reader is no longer left inferring reachability from an address that does
not support the inference. The field itself is still the HTTP-fallback dial target, which is
correct for same-host and containerised deployments and is the only thing that path serves.

---

## Features in dependency order

Each item lists what must exist before it. Status is one of
**done** / **partial** / **not started**.

### Stage 0 — Stop the bleeding

| # | Feature | Status | Depends on |
|---|---------|--------|-----------|
| 0.1 | **Scheduler authenticates to nodes.** The node's `/infer` requires `X-Network-Auth-Token` and fails closed; the Scheduler proxied with no headers, so every real request 401d. Resolved as **per-node** tokens, captured from the registration request and stored outside the `Node` model so they cannot be serialised into an API response. A fleet-wide token remains as a fallback. Both proxy call sites fixed — `openai.py` and `schedule.py`. | **done** | — |

### Stage 1 — Make the core loop work across two machines

| # | Feature | Status | Depends on |
|---|---------|--------|-----------|
| 1.1 | **Node reachability.** Resolved by routing inference over the Zenoh session the node already dials out and holds: the node declares a queryable on `public-intelligence/net/{node_id}/infer`, the Scheduler queries it, replies return over the node's own outbound connection. No inbound port, no relay to operate. Preferred whenever the registry has *observed* that node on the mesh, with HTTP kept as the fallback for same-host and containerised deployments. Authenticated by HMAC proof of possession rather than by sending the node's token, since Zenoh links are plaintext by default. Covered by a real-router end-to-end test, not mocks. See `specs/node-reachability.md`. | **done** | 0.1 |
| 1.2 | **Real hardware advertisement.** Registration hardcoded `{"name": "unknown", "vram_total_gb": 16.0, "vram_available_gb": 16.0}` for every node, so matchmaking filtered and scored against fiction. Now measured on the host by `node/core/hardware.py`: NVIDIA via `nvidia-smi`, else Apple Silicon unified memory (Metal genuinely allocates from it), else `cpu-only` at 0 GB. `NodeInfo` carries a real `gpu`; `ram_total_gb` comes from psutil. Scheduler `GPUInfo.vram_total_gb` relaxed `gt=0` → `ge=0`, since that invariant held only because every node lied to satisfy it — a CPU-only node is now representable and is filtered out of any task with a VRAM floor. Every probe degrades to `cpu-only` rather than blocking startup. `GET /nodes` also gained `reachability` (`mesh`/`http`), derived from the registry, so a `127.0.0.1` `ip_address` no longer implies dialability. See `specs/real-hardware-advertisement.md`. | **done** | 1.1 |
| 1.3 | **Real heartbeat metrics.** Heartbeats returned five constants marked "(placeholders)". Two live consequences, both now covered by tests that pin the old behaviour: every node was excluded from any task carrying `min_vram_gb` (the matchmaker prefers the heartbeat's `vram_available_gb`, always `0.0`), and every node scored identically at `0.215`, so selection was really "first registered" and a saturated node was as likely to be picked as an idle one. Now measured via `detect_host_metrics`, sharing `_probe_gpu` with registration so the static and live figures cannot disagree. Apple Silicon GPU utilisation comes from `ioreg` (no sudo needed); `queue_length` is the real queue depth. **The Scheduler needed no change** — it was always correct and was being fed constants. See `specs/real-heartbeat-metrics.md`. | **done** | 1.2 |
| 1.4 | **Model catalogue is truthful.** `list_models()` had exactly one caller — `Runtime.start()` — so the catalogue froze at node startup. An `ollama pull` was unroutable and an `ollama rm` left the Scheduler advertising a model whose weights were gone, then dispatching to it; restarting the node fixed neither, because re-registration is a create that answers 409 and heartbeats carry no model list. The node now re-reads Ollama on `model_refresh_interval_seconds` (default 60) and pushes to a new `PUT /nodes/{id}/models` **only when the names changed** — a reorder or a size change is not a change. An unreachable Ollama keeps the previous catalogue rather than unadvertising the node, and a failed push is retried rather than assumed. A 409 at registration now triggers an immediate push, which is what makes a restart corrective. Also removed `Settings.hosted_models`: a config-declared model list, documented in `.env.example`, that did not control what the node advertised. See `specs/truthful-model-catalogue.md`. | **done** | 1.2 |
| 1.5 | **Cross-machine integration test.** `tests/test_mesh_inference_e2e.py` now drives a real Zenoh router with no transport mocks, so 1.1 silently breaking would fail a test. What it does not cover is two *machines*: it is one process on TCP loopback, so real RTT, packet loss, and an actual NAT are still unexercised — and that is exactly what would substantiate "a remote node served a request". `docker-compose.test.yml` still has never run and its `NODE_ID` env var is wrong (needs `NODE_NODE_ID`). | **partial** | 1.1 |
| 1.6 | **Node survives a Scheduler outage.** `runtime.start()` let `SchedulerError` propagate out of the FastAPI lifespan, so uvicorn reported "Application startup failed. Exiting." and a host booting during a Render cold start got no process at all. Registration failure is now non-fatal: the node starts, serves its own API, and a background task retries with exponential backoff and **full jitter** (the fleet all retries the moment a Scheduler returns, so plain backoff would land a synchronised herd on it), capped at `registration_retry_max_seconds`. **Widened past "at boot" deliberately**: `/heartbeat` 404s for a node the registry has lost, and the registry is an in-memory dict, so *every* Scheduler restart made *every* node heartbeat into a 404 forever with no recovery but a manual restart. A 404 heartbeat now re-arms the same retry path. Only `SchedulerError` is survivable — a bug in the node still aborts startup. `SchedulerError` gained `status_code`, replacing a `"409" in str(e)` check that also mistook any 500 whose body mentioned 409 for "already registered". See `specs/scheduler-outage-resilience.md`. | **done** | 0.1 |

### Stage 2 — Survive contact with reality

| # | Feature | Status | Depends on |
|---|---------|--------|-----------|
| 2.1 | **Persistence.** `NodeRegistry` and `CreditLedger` were in-memory dicts; every restart lost the fleet and every balance. Both now write through to a `SchedulerStore` (`Protocol`, SQLite implementation, stdlib only) and reload at startup. **The framing in this line was stale and is corrected in the spec:** since 1.6 a node re-registers itself when its heartbeat 404s, so the registry is *reconstructible* and losing it is a recovery window — the **ledger is the unrecoverable half**, because nothing but the Scheduler ever knew a balance. Persisted: nodes, and the per-node credentials without which a restored fleet only 401s. Deliberately **not** persisted: heartbeats, telemetry, `_mesh_nodes`, dampeners. The rule is *persist facts, not observations* — mesh reachability is evidence of a Zenoh session that died with the process, and restoring it would make dispatch prefer a queryable that no longer exists, paying the 5s first-reply timeout on every request. Off by default: a default path on an ephemeral filesystem (Render free tier) survives a process restart and is wiped by every redeploy, which is durability that looks like it works. `create_app()` never reads the setting, so no ambient `.env` can point the test suite at one shared database. See `specs/scheduler-persistence.md`. | **done** | 1.1 |
| 2.2 | ~~**Rotate `TELEMETRY_SECRET_KEY`.**~~ **Superseded by 2.6/2.7 below — do not do this as written.** The default is a constant published in this repo, in both services, so anyone can forge telemetry for any node and steer matchmaking. But rotating it closes nothing: the mesh heartbeat path next to it takes no authentication at all and reaches the same registry state, and the key is fleet-wide symmetric so any participant can forge for any other node regardless. See 2.7. | **superseded** | — |
| 2.3 | **Fix CORS.** **This line's own premise was wrong, and the truth was worse.** It said `allow_origins=["*"]` with `allow_credentials=True` is "rejected by browsers" — i.e. that it failed *safe*. Measured against the real middleware: Starlette does not send a wildcard when credentials are enabled, it **reflects the caller's own `Origin`** and sets `allow-credentials: true`. So it worked perfectly, for every origin that asked, in both services — and with `allow_headers=["*"]` any page could preflight an `Authorization` header and read the reply. The cost is not session riding (these APIs use header tokens, not cookies) but the *unauthenticated* surface: a Scheduler on localhost or a private network was readable by any page an operator visited. Now an explicit allowlist, and with none configured the middleware is **not installed at all** — correct for every current deployment, since every browser fetch in `packages/website` goes to a same-origin Next.js route that reaches these services server-side. `*` in the list is a startup error naming the reflection behaviour, so the trap cannot be walked back into. See `specs/close-the-open-http-surface.md`. | **done** | — |
| 2.4 | **Authenticate `/v1/batch`.** Both routes had no auth dependency while their sibling `/v1/chat/completions` required an RS256 JWT. Now both take `Depends(verify_jwt)`. Authentication alone would have meant "any valid token reads every batch", because a batch carried no owner — so a batch now records the submitting `tenant_id` (outside the response model, like the registry's per-node tokens) and another tenant gets **404, not 403**, with an identical body template: 403 would confirm the id exists and make the endpoint an enumeration oracle. Also fixed here because 2.4's own rejection test depended on it: `verify_jwt` used `Header(...)`, so a request with no `Authorization` was rejected by FastAPI as a **422 validation error** rather than a 401 — on every route depending on it, including the gateway's main one. `_BATCH_TASKS` moved from module scope to `app.state`, **which unblocks the batch persistence 2.1 deferred**. Note: `submit_batch_job` still fabricates its results and dispatches nothing — this secured a stub, it did not implement it. | **done** | — |
| 2.5 | **Node eviction is trustworthy.** Deathrattle and stale-eviction now apply correctly, but `_process_deathrattle` logs success unconditionally. Failures should be visible. | **partial** | 2.1 |
| 2.6 | **Authenticate the read surface.** Found while doing 2.3, recorded rather than absorbed into it. `GET /nodes`, `GET /nodes/{id}`, `GET /v1/models`, `GET /v1/models/{id}` and `GET /status` take no auth dependency, so the node registry — hostnames, regions, IP addresses, GPU models, per-node model catalogues — is readable by anyone who can reach the Scheduler. Not fixed under 2.3 because it needs a decision 2.3 does not contain: model discovery is public on the real OpenAI API, so `/v1/models` may be *meant* to be open while `/nodes` plainly is not. Closing CORS reduced the blast radius from "any web page an operator visits" to "anyone who can reach the host"; it did not close this. | **not started** | — |
| 2.8 | **The installer actually installs.** `install.sh` exited 1 on its first write — the monorepo migration renamed `Node/` to `packages/node/` and left `install.sh`, `scripts/launch_host_node.sh` and both `install.ps1` copies pointing at the old layout. **Nobody could install a node on macOS or Linux, and CI was green over it for two days**, because the only installer check was `install.sh --dry-run` and every step of that script returns early in dry-run mode *after printing what it would do*. Windows was worse than broken: `install.ps1` found no `pyproject.toml` at the repo root, fell through to its clone branch, and installed the **archived pre-monorepo repo** — no error, just a node frozen before 1.4, 1.6, 2.1, 2.3 and 2.4. A second `install.ps1` under `packages/node/` had drifted into never generating `NODE_NETWORK_AUTH_TOKEN`, which the control API fails closed without (0.1), so that copy produced a node serving nothing; deleted. The fix that matters is not the paths but `scripts/verify_install.sh`, a gate step that runs the installer for real against a throwaway copy and asserts the result imports — **its first run immediately found a third bug** the dry-run never could: `packages/node` imported `structlog` and `httpx` without declaring them, resolving only because the shared dev venv has both. See `specs/installer-actually-installs.md`. | **done** | — |
| 2.7 | **Authenticate the Zenoh mesh ingress.** Supersedes the original 2.2 ("rotate `TELEMETRY_SECRET_KEY`"), which does not close the hole it names. Two findings: (a) `_process_heartbeat` accepts **plain unsigned JSON** on `net/*/heartbeat` and the node publishes it unsigned, so an attacker who can no longer forge telemetry simply forges a heartbeat and reaches the same `_heartbeats` state and the same `mark_mesh_reachable`; (b) the telemetry key is **fleet-wide symmetric**, so a merely-secret key stops outsiders but not participants — every host holds it — and the installer cannot generate it per install the way it does `NODE_NETWORK_AUTH_TOKEN`. The fix is to drop the shared key and authenticate telemetry *and* mesh heartbeats with an HMAC over each node's own per-install credential, which the Scheduler already stores from registration and which 1.1 already uses this way for mesh inference. Pre-alpha is the cheapest this wire-format change will ever be. | **not started** | 0.1 |

### Stage 3 — A stranger can actually use it

| # | Feature | Status | Depends on |
|---|---------|--------|-----------|
| 3.1 | **Requester credential issuance.** The gateway verifies RS256 JWTs, but there is no way for a user to obtain one. `scripts/mint_token.py` is an operator tool. Without this there are no requesters — only you. | **not started** | 2.1 |
| 3.2 | **Usage metering.** Record what each request consumed and which node served it. Prerequisite for both billing and host payout. | **not started** | 3.1 |
| 3.3 | **Credit ledger wired.** `CreditLedger` is defined and unit-tested but never instantiated in the app. Hosts currently earn nothing. | **partial** | 3.2 |
| 3.4 | **Host dashboard shows real earnings and history.** Currently shows live telemetry only. | **partial** | 3.3 |
| 3.5 | **Dashboard credential UX.** `NODE_AUTH_TOKEN` must currently be copied by hand from `Node/.env`. Acceptable for you, not for a contributor. | **partial** | 1.1 |
| 3.6 | **Honest docs.** README, quickstart, and `docs/` still describe sharding, FP8, and speculative decoding as realized. A new host reading them will expect a different product. | **not started** | — |

### Stage 4 — Confidence to leave it running

| # | Feature | Status | Depends on |
|---|---------|--------|-----------|
| 4.1 | **Website test infrastructure.** Zero tests exist. The playground, proxies, and SSE parsing are unverified. | **not started** | — |
| 4.2 | **Operational visibility.** Structured logs exist; no aggregation, no alerting. You currently learn something broke by reading CI. | **not started** | 2.1 |
| 4.3 | **Graceful degradation.** Behaviour when no node has the model, when a node dies mid-stream, when Ollama is down. Partly handled (503s), never tested end-to-end. | **partial** | 1.5 |

---

## Definition of done for v1

All of Stages 0–3 at **done**, and this specific walkthrough passing on real
hardware, unassisted:

1. A person on a home connection runs the installer on a machine with a GPU.
2. Their node appears in the Scheduler registry with its **real** GPU, VRAM, and
   model list.
3. A developer on a different network, with a credential they obtained
   themselves, sends an OpenAI-compatible request naming a model that host serves.
4. The request reaches that node, Ollama runs it, tokens stream back.
5. The host sees the request in their dashboard and their credit balance increases.
6. The Scheduler is restarted; hosts and balances survive.

Stage 4 is not a gate for v1, but 4.1 should land before anyone else depends on
the dashboard.

---

## Deliberately not in v1

Layer sharding and split-inference · FP8 activation compression · speculative
decoding · KV-cache checkpointing and pipeline restitching · Raft multi-node
consensus (single instance is the deployment; the code stays, unexercised) ·
Apple Silicon-specific scheduling · fiat payment rails (credits accrue; cashing
out is v2) · the autonomous agent orchestrator.
