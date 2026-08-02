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

**The blocker nobody has hit yet:** every node installed by `install.sh` registers
`ip_address = 127.0.0.1` (`Node/src/node/runtime.py:252`, `install.sh:277`). The
Scheduler builds `http://127.0.0.1:8080/infer` and dials itself. **No remote node
has ever served a request.** Every green test exercises one process talking to
itself.

That single fact is why v1 is defined around delivery and reachability rather than
around inference performance.

---

## Features in dependency order

Each item lists what must exist before it. Status is one of
**done** / **partial** / **not started**.

### Stage 0 — Stop the bleeding

| # | Feature | Status | Depends on |
|---|---------|--------|-----------|
| 0.1 | **Scheduler authenticates to nodes.** `openai.py:427,487` proxy to `/infer` with no headers; the node now requires `X-Network-Auth-Token` and fails closed, so every real request 401s. A regression introduced in this session, hidden because Scheduler tests mock httpx and Node tests bypass auth. Needs a decision: shared `NETWORK_AUTH_TOKEN` across the fleet (what `AliasChoices` in both configs implies) vs. per-node tokens registered with the Scheduler. | **not started** | — |

### Stage 1 — Make the core loop work across two machines

| # | Feature | Status | Depends on |
|---|---------|--------|-----------|
| 1.1 | **Node reachability.** The Scheduler cannot dial a residential node behind NAT. The Zenoh mesh already solves this for telemetry — nodes dial *out* and hold a session. Route inference requests over the existing Zenoh channels instead of HTTP dial-back, or define an explicit relay. This is the single largest piece of v1. | **not started** | 0.1 |
| 1.2 | **Real hardware advertisement.** Registration hardcodes `{"name": "unknown", "vram_total_gb": 16.0, "vram_available_gb": 16.0}` (`clients/scheduler.py:96`), so matchmaking filters on fiction. `telemetry/collector.py` already does real nvidia-smi parsing — wire it to registration. | **partial** | 1.1 |
| 1.3 | **Real heartbeat metrics.** `runtime.py:264-275` returns hardcoded literals (`cpu 15.0`, `vram_available_gb 0.0`) marked "(placeholders)". The scheduler's fitness scoring consumes these, so scoring is currently meaningless. | **partial** | 1.2 |
| 1.4 | **Model catalogue is truthful.** A node should advertise what Ollama actually has pulled, and refresh it when that changes. | **partial** | 1.2 |
| 1.5 | **Cross-machine integration test.** Two processes, real HTTP/Zenoh, no mocks. Nothing today would catch 1.1 breaking again — `docker-compose.test.yml` exists but has never run and its `NODE_ID` env var is wrong (needs `NODE_NODE_ID`). | **not started** | 1.1 |
| 1.6 | **Node survives a Scheduler outage at boot.** `main.py:29` calls `runtime.start()` in the lifespan, which registers with the Scheduler; `SchedulerError` propagates and uvicorn reports "Application startup failed. Exiting." A host whose node boots while the Scheduler is briefly down (Render cold start, network blip) just gets a dead process. Needs retry with backoff and a degraded start. Found while verifying 0.1. | **not started** | 0.1 |

### Stage 2 — Survive contact with reality

| # | Feature | Status | Depends on |
|---|---------|--------|-----------|
| 2.1 | **Persistence.** `NodeRegistry` and `CreditLedger` are in-memory dicts. Render restarts and every host, every balance, every batch job is gone. Nothing else in Stage 3 can be trusted without this. | **not started** | 1.1 |
| 2.2 | **Rotate `TELEMETRY_SECRET_KEY`.** Defaults to `pi_telemetry_secure_default_secret_key`, published in this repo, in both services. Anyone can forge telemetry for any node and steer matchmaking. | **not started** | — |
| 2.3 | **Fix CORS.** `allow_origins=["*"]` with `allow_credentials=True` in both services — rejected by browsers and wrong in intent. | **not started** | — |
| 2.4 | **Authenticate `/v1/batch`.** `POST /v1/batch` and `GET /v1/batch/{id}` have no auth dependency at all. | **not started** | — |
| 2.5 | **Node eviction is trustworthy.** Deathrattle and stale-eviction now apply correctly, but `_process_deathrattle` logs success unconditionally. Failures should be visible. | **partial** | 2.1 |

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
