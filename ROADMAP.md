# ROADMAP — v1

Status: **Stage 0-2 built. Stage D open, and it gates everything below it.**

This supersedes `docs/ROADMAP.md`, which describes phases 4.6–4.9 as "Realized"
based on code that does not do what the labels claim. Where the two disagree,
this file is correct. (`docs/` still makes those claims to anyone who reads it —
that is item N2 below.)

**A full audit on 2026-08-07 found that the engineering is ahead of the product
definition.** Ten items shipped across Stages 0–2; meanwhile the production network
does not exist, the API can return fabricated text as a successful completion, and
the central question a compute marketplace has to answer — how a requester knows a
node really ran the model — is not on this roadmap at all. Stage D was added in
front of everything as a result. **No further feature work starts until D is
answered**, with the deliberate exception of the three no-regret fixes.

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

### Stage D — Decide what this is (blocks everything below)

Not code. These are the questions the code has been assuming answers to. Each one
is cheap to answer on paper and expensive to answer wrong after another month of
building. **Nothing in Stages 0–4 should be started until D1–D3 are settled**, because
each of them can change what the right system looks like.

**Answered 2026-08-07.** Seven of the eight are decided; the records are in
[`docs/decisions/`](docs/decisions/README.md) and each one states what it costs and
what changes in the code. Two of them cut scope that was already on this page: **D2
found the economics do not close**, so Stage 3's payout machinery is gone and credits
are an accounting unit; **D6 found there is no network and decided not to build one**,
which unblocks C1 in the opposite direction from the one it assumed. **D7 stays open
on purpose** — it asks for a second party, and an answer from the party asking is the
failure mode rather than the fix.

The original question text is kept inline below each decision rather than replaced,
because a decision record without the question it answered rots faster than the code.

| # | Decision | Why it blocks | Status |
|---|---------|---------------|--------|
| D1 | **DECIDED: invite-only trusted hosts, plus sampled canary verification.** See `docs/decisions/D1-execution-integrity.md`. Original question: **How does a requester know a node actually ran the model?** In a network of untrusted hosts this is the core problem, and there is no answer today: no redundant execution, no canary prompts, no attestation, no reputation grounded in anything checkable. The `token_556` bug (N1) is the accidental version of this; the adversarial version is a host returning cheap garbage to earn credits, which is rational for them and undetectable by us. Petals survives without this because participants are semi-altruistic researchers — **attaching payment invites cheating.** Acceptable answers include "trusted/invite-only hosts for v1", sampled redundant execution, or canary prompts. Having no answer is not one. | Determines whether v1 is a marketplace or a trusted-host network, which changes matchmaking, the ledger, and the pitch. | **decided** |
| D2 | **DECIDED: no — the economics do not close.** A consumer-GPU host loses 15x against commodity pricing once hardware amortisation is counted, and break-even utilisation is unreachable at any load. v1 is a **donation network**: credits are an accounting unit, payouts are cut. Model in `scripts/economics.py`, conclusion pinned by `tests/test_economics.py`. See `docs/decisions/D2-economics.md`. Original question: **Do the economics close?** One spreadsheet: a host's electricity cost per 1M tokens on consumer hardware, versus current commodity API pricing. Inference prices have collapsed; if a host loses money per token, this is a donation network rather than a marketplace — a legitimate thing to be, but a different product with a different design and a different pitch. | If hosts cannot profit, Stage 3 (credentials, metering, ledger, payouts) is building the wrong thing. | **decided** |
| D3 | **DECIDED for the self-hosted scope, and NOT reviewed by counsel.** Exposure collapsed by narrowing the product (D6 removes the operated service), then documented: Apache-2.0 disclaimer, `docs/OPERATING.md`, `docs/ACCEPTABLE_USE.md`, and metering that records no prompt text. **Operating this for other people is still gated on real legal advice.** See `docs/decisions/D3-terms-and-liability.md`. Original question: **Terms of service, acceptable use, and operator liability.** Hosts run arbitrary prompts from strangers on home machines, egressing from a residential IP. There is no ToS, no AUP, no abuse pipeline, no content policy. Separately, prompts are personal data routed to unvetted third parties worldwide with no DPA and no real residency control (`region` is self-asserted). | Existential and much cheaper to settle on paper than in court. Needs actual legal advice, not a guess. | **decided (partial — legal review outstanding)** |
| D4 | **DECIDED: invite codes at registration**, hashed at rest, single-use by default, revocable, with the admitting code recorded per node. Open registration remains possible but logs a loud startup warning rather than being a silent fallback. See `docs/decisions/D4-sybil-resistance.md`. Original question: **Sybil resistance.** Registration costs nothing and anyone can register N nodes and receive dispatch. 1.2 made *honest* nodes report real hardware; a malicious host patches their own copy. Invite-only onboarding is the cheap v1 answer. | Determines whether node identity needs stake, vetting, or attestation. | **decided** |
| D5 | **DECIDED: narrow the claim** to "community-hosted compute, coordinated by one control plane you run yourself". The word *decentralised* is dropped, because the coordinator is a single point of trust. Raft stays in the tree, quarantined to `experimental/` (C2). See `docs/decisions/D5-decentralisation-claim.md`. Original question: **"Decentralised" versus one instance.** The pitch is community-owned decentralised infrastructure. The architecture is a single control plane holding all state in memory on a free tier. The Raft code exists and is explicitly out of v1. Either the claim narrows or the architecture changes. | Same failure mode as the docs: a story the system does not implement. | **decided** |
| D6 | **DECIDED: there is no network, and one will not be operated.** Ship a self-hosted product; the installer defaults to `localhost` and a remote Scheduler becomes an explicit act. No domain is registered. See `docs/decisions/D6-is-there-a-network.md`. Original question: **Is there a network at all, and who runs it?** `bootstrap.public-intelligence.net` and `public-intelligence.net` are **NXDOMAIN**; the hosted Scheduler did not respond in 120s. Every installer-provisioned node points at all three. Decide: register and operate a real network, or ship a self-hosted product and change the installer defaults. The current state is the worst of both. | C1 cannot be executed until this is decided. | **decided** |
| D7 | **OPEN, and not closable from inside — deliberately left open.** An answer produced by the party asking is the failure mode, not the fix. Substitutes shipped instead: `docs/PREMISES.md`, a register of every load-bearing assumption with its falsifier and confidence, so a reviewer can attack the premises directly. See `docs/decisions/D7-second-pair-of-eyes.md`. Original question: **A second pair of eyes.** The process here — `VERIFY.md`, the drift ratchets, red-green with mutation testing — is stronger than most production teams have. It catches regressions and is structurally incapable of catching a wrong premise: it did not notice the dead DNS, the reachable simulation path, or the missing licence, because it was not looking. Every judgement to date has been made by one party. | Determines whether D1–D6 get reviewed by anyone who can say "this premise is wrong". | **OPEN** |
| D8 | **DECIDED: an OpenAI-compatible control plane for hardware you already own.** The marketplace framing lost on every axis to an incumbent and was ruled out arithmetically by D2. The differentiator is NAT traversal for GPU hosts — which is also the least substantiated claim in the project (1.5 is partial), so 1.5 is promoted. See `docs/decisions/D8-the-wedge.md`. Original question: **The wedge.** Petals, Together, Akash, io.net, Prime Intellect, Hyperbolic, Bittensor. Write the one paragraph explaining why someone picks this instead. If it is hard to write, that is the finding. | Everything in Stage 3 is go-to-market machinery for a position not yet articulated. | **decided** |

### No-regret fixes (do not wait for Stage D)

These are wrong under **every** possible answer to D, so sequencing them behind it
would be false discipline.

| # | Fix | Status |
|---|-----|--------|
| N1 | **The API returned fabricated text as a successful completion.** A valid JWT plus `x-split-inference: true` asking "What is the capital of France?" returned **HTTP 200** with `content: 'token_556'` in the standard OpenAI response shape, so every compatible client would show it to a user as the model's answer. It routed to `LocalBoundaryEngine`, seeded `random.gauss` matrices over a toy vocabulary. Now **501 Not Implemented** — the server understands the request and has no implementation; a 400 would blame the caller and silently serving a non-split completion would tell them they got what they asked for. The ~250-line execution block was **deleted**, not left behind the guard, because dead code behind a disabled flag is exactly how this happened. Also found while fixing it: `enable_split_inference`, one of the three triggers, **is not a field on `Settings` and never was** — that branch could never fire, so an operator setting it got nothing, silently. See `specs/stop-returning-fabricated-completions.md`. | **done** |
| N2 | **`docs/` advertised the cut features as shipped.** `ARCHITECTURE_OVERVIEW.md:60` claimed FP8 E4M3 "integrated", `:94` said "realized through Phase 4.5", `docs/ROADMAP.md` said "v0.1 (Realized)" and "v0.2 (Realized)", `PROJECT_CONTEXT.md` promised layer sharding. A visitor read those, enabled the flag from N1, and got noise. Moved to `docs/historical/` behind a header that tabulates each false claim against reality — kept rather than deleted, because the reasoning is worth having and the history should not pretend they never existed. **Also found: there was no `README.md` at all**, so `docs/` was the only thing describing the project. A minimal one now states what is verified, what does not work and is not claimed to, and defers the product definition to Stage D rather than inventing an answer. | **done** |
| N3 | **No LICENSE, CONTRIBUTING, or SECURITY policy.** Default copyright is all-rights-reserved, so nobody may legally fork, contribute to, or run this — which contradicts the community-owned positioning outright. No disclosure path for security reports either. Fixed: **Apache-2.0** with `NOTICE`, plus `SECURITY.md` (honest response times for a one-person pre-alpha project, and it scopes the known-unfixed list in `VERIFY.md` step 3 explicitly *out* of what needs reporting) and `CONTRIBUTING.md`. Note what this unblocks that is not obvious: **until now nobody could legally fork this to critique it**, which is a precondition for D7. | **done** |

### Stage C — Correctness debt found in the 2026-08-07 audit

Real defects, none of them blocking D, all of them worth fixing once D says what
this is. Sequenced after D deliberately: several change shape depending on the
answers.

| # | Item | Depends on |
|---|------|-----------|
| C1 | **Make the deployment real, or stop shipping one.** Register the domain and stand up the bootstrap router and Scheduler, or change installer defaults to `localhost`. Today `install.sh` writes a dead Scheduler URL and a non-resolving Zenoh bootstrap into every `.env` it generates. | D6 |
| C2 | **Quarantine the cut-feature code.** ~2,850 lines across `local_boundary` (756), `transport` (1,082), `consensus` (530), `kv_cache` (197), `quantization` (98), `autonomous_orchestrator` (172) — shipped, tested by ~40 test files, and in `local_boundary`'s case reachable from the public API. Move to `experimental/`, exclude from the gate, and report the shipping-code test count separately so a green number means something. | N1 |
| C3 | **Persistence is off by default, so nothing persists.** 2.1 made it opt-in for good reasons (ephemeral filesystems), but no deployment sets `SCHEDULER_DATABASE_PATH`. Either default it on with a real disk, or state plainly in `STATUS.md` that no deployment persists. | D6 |
| C4 | **One signing key, no rotation, no revocation.** Add `kid` to issued JWTs and support two active keys, before it is needed rather than after. The hardcoded fallback public key at `ingress.py:16` is the related known issue. | — |
| C5 | **The rate limiter is in-memory and per-instance.** Capacity 5, refill 0.5/s, resets on restart, would not hold across replicas. Fine for one instance; not a quota. | D5 |
| C6 | **`packages/website` has zero tests** — `package.json` has `lint` and no `test`. Duplicate of 4.1, restated because the 2.6 proxy change is unverified by anything. | — |
| C7 | **The gate does not type-check `tests/` and does not touch the website at all.** 2.9 closed the lint half; mypy and the website remain outside "the only definition of does this pass". | — |
| C8 | **Dead and duplicated code.** `src/shared/` is an orphan third copy of the artifact store, imported by nothing. Six duplicated module pairs remain, and `packages/shared/` — the stated follow-up to the monorepo migration — still does not exist. | C2 |
| C9 | **Batch jobs are still not persisted**, now unblocked by 2.4 moving them off module scope. | C3 |
| C10 | **Revisit `/v1/models` being public.** A deliberate 2.6 decision on the argument that a marketplace should let a developer see what is servable. It also discloses fleet composition, and the tradeoff changes once there is a real fleet. | D1 |

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
| 2.2 | ~~**Rotate `TELEMETRY_SECRET_KEY`.**~~ **Superseded by 2.7, which is now done.** The default is a constant published in this repo, in both services, so anyone can forge telemetry for any node and steer matchmaking. But rotating it closes nothing: the mesh heartbeat path next to it takes no authentication at all and reaches the same registry state, and the key is fleet-wide symmetric so any participant can forge for any other node regardless. See 2.7. | **superseded** | — |
| 2.3 | **Fix CORS.** **This line's own premise was wrong, and the truth was worse.** It said `allow_origins=["*"]` with `allow_credentials=True` is "rejected by browsers" — i.e. that it failed *safe*. Measured against the real middleware: Starlette does not send a wildcard when credentials are enabled, it **reflects the caller's own `Origin`** and sets `allow-credentials: true`. So it worked perfectly, for every origin that asked, in both services — and with `allow_headers=["*"]` any page could preflight an `Authorization` header and read the reply. The cost is not session riding (these APIs use header tokens, not cookies) but the *unauthenticated* surface: a Scheduler on localhost or a private network was readable by any page an operator visited. Now an explicit allowlist, and with none configured the middleware is **not installed at all** — correct for every current deployment, since every browser fetch in `packages/website` goes to a same-origin Next.js route that reaches these services server-side. `*` in the list is a startup error naming the reflection behaviour, so the trap cannot be walked back into. See `specs/close-the-open-http-surface.md`. | **done** | — |
| 2.4 | **Authenticate `/v1/batch`.** Both routes had no auth dependency while their sibling `/v1/chat/completions` required an RS256 JWT. Now both take `Depends(verify_jwt)`. Authentication alone would have meant "any valid token reads every batch", because a batch carried no owner — so a batch now records the submitting `tenant_id` (outside the response model, like the registry's per-node tokens) and another tenant gets **404, not 403**, with an identical body template: 403 would confirm the id exists and make the endpoint an enumeration oracle. Also fixed here because 2.4's own rejection test depended on it: `verify_jwt` used `Header(...)`, so a request with no `Authorization` was rejected by FastAPI as a **422 validation error** rather than a 401 — on every route depending on it, including the gateway's main one. `_BATCH_TASKS` moved from module scope to `app.state`, **which unblocks the batch persistence 2.1 deferred**. Note: `submit_batch_job` still fabricates its results and dispatches nothing — this secured a stub, it did not implement it. | **done** | — |
| 2.5 | **Node eviction is trustworthy.** **This line carried two wrong claims over its life, both corrected rather than inherited.** It first said stale-eviction "now applies correctly" when nothing aged nodes out at all — 2.7 built that mechanism. What survived was the original complaint in its final form: `unregister_node` returned `None`, so the router logged `zenoh_node_evicted_stale` on the strength of having *asked*, and on the consensus path asking does not touch the registry at all. The removal methods now report whether the node is actually gone — and on the consensus path, where a dropped or election-lost proposal is indistinguishable from an applied one, they report whether the node is absent *afterwards* rather than claiming to have removed it. A removal that changed nothing logs a warning instead of a success. The graceful `DELETE /nodes/{id}` path, which said nothing at all, now logs too, so "where did node X go" is one grep rather than an inference from absence. See `specs/eviction-reports-what-it-did.md`. | **done** | 2.1 |
| 2.6 | **Authenticate the read surface.** `GET /nodes`, `/nodes/{id}`, `/nodes/telemetry`, `/nodes/{id}/telemetry` and `/status` took no auth dependency at all, so anyone who could reach the Scheduler got every hostname, IP, region, GPU model, model catalogue and **live decrypted per-node metric**. **This line named five routes and missed the two that mattered most:** `/nodes/telemetry` returns the whole `_telemetry` dict — the data 2.7 had just spent a protocol change protecting *in transit*. Authenticating the mesh while serving the same metrics to anyone over HTTP was half a fix. All now carry `verify_auth_token`, the dependency their siblings in the same routers already had. `/health` and `/health/ready` stay public (probes; one that needs a secret reports unhealthy when the secret is wrong) and `/v1/models` stays public as a stated judgement — a marketplace should let a developer see what is servable before obtaining a credential, and it discloses names only, not which node has what. The durable part is a **route-inventory ratchet** that fails when any new unguarded route appears off an explicit allowlist, so the next one is caught when it is added rather than two roadmap items later. See `specs/authenticate-the-read-surface.md`. | **done** | — |
| 2.9 | **Lint the cross-package tests, and catch implicit text encodings.** Both gaps found the hard way: 2.7 passed the local gate and the pre-push hook, then failed CI on all three Windows legs, because `Path.read_text()` with no encoding resolves to the platform default — UTF-8 here, cp1252 there — and one non-ASCII byte in a scanned file broke it. (a) `scripts/verify.sh` linted `./packages` and **never looked at the root `tests/` directory at all** — the wire contract, every ratchet, the installer checks — so a whole directory sat outside "the only definition of does this pass" while appearing to be inside it. Now linted and format-checked using the scheduler package's config rather than a third copy of it. (b) Ruff's `PLW1514` is enabled via `explicit-preview-rules`, so exactly one preview rule activates rather than every preview rule in the selected categories. It found **2** violations, one of them production code (`open("/proc/meminfo")` on the Linux telemetry path). `tests/` had 7 real lint errors, not the 22 I first reported — that count came from running ruff at its default line length instead of this repo's, and is corrected here. Gate is 15 checks, up from 13. See `specs/lint-the-tests-and-the-encodings.md`. | **done** | — |
| 2.10 | **The orchestrator claims verification it never ran.** `AutonomousOrchestrator.execute_mission` returns `verification_passed=True` and a body reading "Closed-loop tri-factor verification (pytest, ruff, mypy) passed cleanly" — for a pure stub that formats strings and runs none of them. Found while doing 2.6. It is currently unreachable (`create_app` does not mount the webhooks router), which bounds the harm but not the dishonesty: this is precisely the class of claim `docs/ROADMAP.md` was superseded for making. The prior question is whether the orchestrator and its webhook belong in v1 at all, given the autonomous orchestrator sits on this file's own "deliberately not in v1" list — deleting them may be the right fix rather than making the stub honest. | **not started** | — |
| 2.8 | **The installer actually installs.** `install.sh` exited 1 on its first write — the monorepo migration renamed `Node/` to `packages/node/` and left `install.sh`, `scripts/launch_host_node.sh` and both `install.ps1` copies pointing at the old layout. **Nobody could install a node on macOS or Linux, and CI was green over it for two days**, because the only installer check was `install.sh --dry-run` and every step of that script returns early in dry-run mode *after printing what it would do*. Windows was worse than broken: `install.ps1` found no `pyproject.toml` at the repo root, fell through to its clone branch, and installed the **archived pre-monorepo repo** — no error, just a node frozen before 1.4, 1.6, 2.1, 2.3 and 2.4. A second `install.ps1` under `packages/node/` had drifted into never generating `NODE_NETWORK_AUTH_TOKEN`, which the control API fails closed without (0.1), so that copy produced a node serving nothing; deleted. The fix that matters is not the paths but `scripts/verify_install.sh`, a gate step that runs the installer for real against a throwaway copy and asserts the result imports — **its first run immediately found a third bug** the dry-run never could: `packages/node` imported `structlog` and `httpx` without declaring them, resolving only because the shared dev venv has both. See `specs/installer-actually-installs.md`. | **done** | — |
| 2.7 | **Authenticate the Zenoh mesh ingress.** Supersedes 2.2 ("rotate `TELEMETRY_SECRET_KEY`"), which closes nothing. All three mesh inputs were forgeable by anyone who could reach the public bootstrap router: telemetry signed with a key whose default is a constant published here; heartbeats accepted as **plain unsigned JSON**; and — the worst — liveliness, where a DELETE took the node id from a key expression *the publisher chose* and called `unregister_node`, so **anyone could evict any host**. Now every message that changes registry state is an AES-256-GCM envelope keyed on that node's own `NODE_NETWORK_AUTH_TOKEN`, which the installer already generates per install and the Scheduler already stores at registration — closing the insider case a fleet-wide secret never could. Liveliness stops mutating state entirely: an unauthenticated signal may accelerate a check, never perform a write. **Absorbed the core of 2.5**, because removing the deathrattle's write without a time-based replacement would have traded an eviction hole for dead hosts advertised forever. See `specs/authenticated-mesh-ingress.md`. | **done** | 0.1 |

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

**Stage D answered, N1–N3 fixed, and all of Stages 0–3 at done** — plus this
specific walkthrough passing on real hardware, unassisted.

Stage D is listed first on purpose. Step 3 below assumes a developer *wants* to
send this request (D8), step 5 assumes a credit is worth something (D2), and the
whole walkthrough assumes the answer arriving in step 4 was really produced by
that node rather than fabricated (D1). Those assumptions were load-bearing and
unexamined for the first eight roadmap items; they are now explicit.

Note also that steps 1–4 currently cannot happen at all: the installer points at a
Scheduler and a bootstrap router that do not resolve (D6/C1).

The walkthrough:

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
