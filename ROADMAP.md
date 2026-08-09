# ROADMAP — v1

Status: **Stage 0-2 built. Stage D answered on 2026-08-07 (D7 excepted); C, 3 and 4 in progress.**

This supersedes `docs/ROADMAP.md`, which describes phases 4.6–4.9 as "Realized"
based on code that does not do what the labels claim. Where the two disagree,
this file is correct. Those documents were moved to `docs/historical/` behind a
header tabulating each false claim against reality (N2, done).

**A full audit on 2026-08-07 found that the engineering was ahead of the product
definition.** Ten items had shipped across Stages 0–2; meanwhile the production network
did not exist, the API could return fabricated text as a successful completion, and
the central question a compute marketplace has to answer — how a requester knows a
node really ran the model — was not on this roadmap at all. Stage D was added in
front of everything as a result.

**Stage D was then answered, and it changed this document.** Seven of the eight
decisions are recorded in [`docs/decisions/`](docs/decisions/README.md). Two of them
cut scope from this page: the economics do not close, so v1 is a donation network and
the payout machinery is gone (D2); and there is no network and one will not be
operated, so this is a self-hosted product (D6). D7 — a second pair of eyes — is
deliberately still open, because it cannot be closed by the party asking.

---

## What v1 is

> **An OpenAI-compatible control plane for hardware you already own.** A person
> runs one command on a machine with a GPU and it starts serving requests. A
> developer points an OpenAI-compatible client at one URL and gets completions back,
> served by a machine they or someone they trust controls — including one behind
> NAT, with no port forwarding. The host can see what their machine did and what it
> contributed.

**This wording changed on 2026-08-07.** It used to read "a decentralised inference
marketplace ... and what it earned". Three words in that sentence were load-bearing
and all three failed: *decentralised* (the coordinator is a single point of trust —
D5), *marketplace* (a host loses ~15x against commodity pricing — D2), and *earned*
(credits are non-redeemable, by decision, not by omission — D2). See
[D8](docs/decisions/D8-the-wedge.md).

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

That is a real product, but **the parenthetical in the original version of this
paragraph was wrong.** It said "the economics of idle consumer hardware stand on their
own". They do not: `scripts/economics.py` puts a realistic host at $2.256 per 1M
tokens against a $0.150 commodity price, and break-even utilisation is unreachable.
That sentence was an assumption stated as a fact for eight roadmap items. See
[D2](docs/decisions/D2-economics.md).

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
| D1 | **DECIDED: invite-only trusted hosts, plus sampled canary verification.** See `docs/decisions/D1-execution-integrity.md`. Original question: **How does a requester know a node actually ran the model?** In a network of untrusted hosts this is the core problem, and there is no answer today: no redundant execution, no canary prompts, no attestation, no reputation grounded in anything checkable. The `token_556` bug (N1) is the accidental version of this; the adversarial version is a host returning cheap garbage to earn credits, which is rational for them and undetectable by us. Petals survives without this because participants are semi-altruistic researchers — **attaching payment invites cheating.** Acceptable answers include "trusted/invite-only hosts for v1", sampled redundant execution, or canary prompts. Having no answer is not one. | Determines whether v1 is a marketplace or a trusted-host network, which changes matchmaking, the ledger, and the pitch. | **decided + implemented 2026-08-09** |
| D2 | **DECIDED: no — the economics do not close.** A consumer-GPU host loses 15x against commodity pricing once hardware amortisation is counted, and break-even utilisation is unreachable at any load. v1 is a **donation network**: credits are an accounting unit, payouts are cut. Model in `scripts/economics.py`, conclusion pinned by `tests/test_economics.py`. See `docs/decisions/D2-economics.md`. Original question: **Do the economics close?** One spreadsheet: a host's electricity cost per 1M tokens on consumer hardware, versus current commodity API pricing. Inference prices have collapsed; if a host loses money per token, this is a donation network rather than a marketplace — a legitimate thing to be, but a different product with a different design and a different pitch. | If hosts cannot profit, Stage 3 (credentials, metering, ledger, payouts) is building the wrong thing. | **decided** |
| D3 | **DECIDED for the self-hosted scope, and NOT reviewed by counsel.** Exposure collapsed by narrowing the product (D6 removes the operated service), then documented: Apache-2.0 disclaimer, `docs/OPERATING.md`, `docs/ACCEPTABLE_USE.md`, and metering that records no prompt text. **Operating this for other people is still gated on real legal advice.** See `docs/decisions/D3-terms-and-liability.md`. Original question: **Terms of service, acceptable use, and operator liability.** Hosts run arbitrary prompts from strangers on home machines, egressing from a residential IP. There is no ToS, no AUP, no abuse pipeline, no content policy. Separately, prompts are personal data routed to unvetted third parties worldwide with no DPA and no real residency control (`region` is self-asserted). | Existential and much cheaper to settle on paper than in court. Needs actual legal advice, not a guess. | **decided (partial — legal review outstanding)** |
| D4 | **DECIDED: invite codes at registration**, hashed at rest, single-use by default, revocable, with the admitting code recorded per node. Open registration remains possible but logs a loud startup warning rather than being a silent fallback. See `docs/decisions/D4-sybil-resistance.md`. Original question: **Sybil resistance.** Registration costs nothing and anyone can register N nodes and receive dispatch. 1.2 made *honest* nodes report real hardware; a malicious host patches their own copy. Invite-only onboarding is the cheap v1 answer. | Determines whether node identity needs stake, vetting, or attestation. | **decided + implemented 2026-08-09** |
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
| C1 | **DONE — `localhost`, per D6.** Both installers now default to `http://localhost:8000` and **no** bootstrap router (empty means scout the local network, which does not dial a host that does not exist), with `--scheduler-url` / `--bootstrap-router` to reach another machine explicitly. Two things fell out that the line did not anticipate: the node's own default `scheduler_url` was `localhost:8080`, which is the **node's** port, so an unconfigured node pointed at itself; and **`install.sh --dry-run` printed values the real run did not write** — `localhost:8080` versus the Render URL — which matters because the dry-run is a gate step, so the gate was verifying a lie. Values are now computed once, above the branch. Ratcheted by `tests/test_installer_defaults.py`. | D6 |
| C2 | **DONE — and the last piece was a live security hole, not tidiness.** `consensus.py` was described here (and by me, in `experimental/README.md`) as inert because the deployment is a single instance. **It was not inert.** `ZenohRouter.start()` constructed and started a `RaftConsensusEngine` on every boot, which opened a second Zenoh session and declared a subscriber on `public-intelligence/net/consensus/*` — **a wildcard key with no authentication** — whose handler took JSON from anyone. `AppendEntries` with a higher term made the Scheduler a follower of the sender and applied the sender's entries: `unregister_node` **evicts any host**, `register` **injects one**, and an injected node is dispatched to, so it receives other people's prompts. 2.7 closed this exact shape for telemetry, heartbeats and liveliness — its summary even says *"anyone could evict any host"* — and never touched the consensus plane. Engine and its `is_active()` branches removed; module and tests quarantined. Earlier: `local_boundary`, `transport`, `boundary_engine`, `kv_cache`, `quantization` moved, each of which also had live defects. | N1 |
| C3 | **DONE — on by default.** 2.1's reasoning was right about the deployment it had: a default path on an ephemeral filesystem survives a restart and is wiped by every redeploy, which is durability that looks like it works. D6 removed that deployment, and the measured consequence of opt-in was that **nothing set it, so nothing persisted anywhere** — losing every credit balance on every restart, the one piece of state nothing can reconstruct. Off is now an explicit empty string that logs a warning naming what is lost. Turning it on exposed a second defect: `SQLiteStore` connected in `__init__` and `main.py` builds the ASGI `app` at module scope, so **importing the module created a database file** wherever the process was running. Connection is now lazy and construction is side-effect-free. | D6 |
| C4 | **DONE.** Issued JWTs carry a `kid` and the Scheduler accepts **two** active keys, so rotation is a sequence rather than an outage: add the new key as secondary, sign with it, retire the old one once the last token under it expires. `kid` is a **hint for key selection, never an assertion of validity** — an unknown one falls through to trying every active key and a token verifying under none is refused, which is the standard way a kid-aware verifier turns into a bypass. **The hardcoded fallback key is gone, and its risk had been misjudged:** the argument for tolerating it was that the matching *private* key is not in this repo, so nobody could mint a token it accepts. True, and beside the point — the key came from somewhere, it is a "standard dummy" PEM of the kind that circulates in tutorials, and whoever generated it may hold the private half. An unconfigured gateway now **fails closed** rather than trusting a key of unknown provenance. | — |
| C5 | **DONE — kept, bounded, and described honestly.** D5 settled that the deployment *is* a single instance, so a per-instance limiter is adequate; the field descriptions now say **per-instance** and "abuse dampener", because calling it a quota would claim a guarantee it cannot make. Two real fixes: the limits were constructor defaults **no operator could reach** (now `SCHEDULER_RATE_LIMIT_CAPACITY` / `_REFILL`), and `buckets` grew one entry per tenant and never shrank. Eviction drops only buckets that have **refilled to capacity** — dropping a depleted one would let a tenant reset their own limit by waiting, which is a rate-limit bypass wearing a cleanup costume, and there is a test for exactly that. | D5 |
| C6 | **`packages/website` has zero tests** — `package.json` has `lint` and no `test`. Duplicate of 4.1, restated because the 2.6 proxy change is unverified by anything. | — |
| C7 | **The gate does not type-check `tests/` and does not touch the website at all.** 2.9 closed the lint half; mypy and the website remain outside "the only definition of does this pass". | — |
| C8 | **DONE.** `packages/shared/` exists and holds `mesh_protocol` and `mesh_auth` as `pi_shared`, with thin re-export shims at the old import paths so ~30 call sites did not have to move in the same change as the code. The byte-identity ratchets are **replaced by a stronger claim** — exactly one copy exists, and the shims stay thin — which needs no drift budget: a pair held at zero is one forgetful commit from drifting, and mesh divergence fails *silently* (the Scheduler simply stops accepting real nodes). Found while doing it: `EXPERIMENTAL_PAIRS` had been declared by C2 and **parametrized over nothing**, so the four quarantined pairs were unratcheted while a commit message said they were. Now merged into one `ALL_PAIRS` parametrisation. Earlier halves: the artifact store's copies went 4 → 1. | C2 |
| C9 | **SUPERSEDED — the persistence gap was not the problem.** `submit_batch_job` **fabricated its results**: every item returned `status_code: 200` with `"[Batch Response for '<your prompt>...'] Completed asynchronously via WAN pipeline"` and `completed_items == total_items`, having contacted no node and run no model. That is ROADMAP N1's defect in a second endpoint, and N1's resolution applies unchanged — **501, and the block deleted rather than guarded.** Persisting this would have made a fabrication durable, not true. 2.4's authentication and tenant scoping are preserved, because they were real fixes to a real hole and are the part that must not be rebuilt from scratch when batch is actually implemented. | C3 |
| C10 | **DONE — now authenticated.** 2.6's argument was that "a marketplace should let a developer see what is servable before obtaining a credential", and its own test closed with *if that judgement is ever reversed, this test is what has to be changed on purpose*. Stage D removed the premise rather than the reasoning: D1 made this invite-only and D8 made it a self-hosted control plane, so the anonymous developer the exception existed for does not exist — anyone who should see the catalogue already holds a credential. Note what did **not** change: the disclosure is still model names only, never which node has what. The exception was reasonable when made; its benefit went away and its cost did not. | D1 |

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
| 1.5 | **STILL PARTIAL, and now the top priority.** `tests/test_mesh_inference_e2e.py` drives a real Zenoh router with no transport mocks, in one process on TCP loopback — real RTT, packet loss and NAT are still unexercised. **`docker-compose.test.yml` has still never been run**, because Docker was unavailable in the environment that last edited it; that is stated in the file itself rather than implied. Two more faults were found in it **without** running it, by `tests/test_compose_env_matches_settings.py`, which checks every variable against the fields the services actually read: `NODE_ZENOH_LISTEN_ENDPOINTS` is a *Scheduler* field the Node has never had (silently ignored, exactly like the `NODE_ID` bug this line already named), and since C4 the file configured no gateway key, so it could only ever have demonstrated 401s. **D8 makes this the load-bearing claim of the whole project** — NAT traversal for GPU hosts is the differentiator, and it is the one thing not demonstrated on real hardware. See `docs/PREMISES.md` P2. | **partial** | 1.1 |
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
| 2.10 | **DONE — deleted, not made honest.** The prior question this line raised answered itself: the autonomous orchestrator is on this file's own "deliberately not in v1" list, so making the claim truthful would have left ~170 lines of unreachable code serving a feature the product has decided not to have. Both copies and `api/webhooks.py` are gone, with a ratchet in `test_read_surface_auth.py` that fails if either module returns. Original finding: **The orchestrator claims verification it never ran.** `AutonomousOrchestrator.execute_mission` returns `verification_passed=True` and a body reading "Closed-loop tri-factor verification (pytest, ruff, mypy) passed cleanly" — for a pure stub that formats strings and runs none of them. Found while doing 2.6. It is currently unreachable (`create_app` does not mount the webhooks router), which bounds the harm but not the dishonesty: this is precisely the class of claim `docs/ROADMAP.md` was superseded for making. The prior question is whether the orchestrator and its webhook belong in v1 at all, given the autonomous orchestrator sits on this file's own "deliberately not in v1" list — deleting them may be the right fix rather than making the stub honest. | **done** | — |
| 2.8 | **The installer actually installs.** `install.sh` exited 1 on its first write — the monorepo migration renamed `Node/` to `packages/node/` and left `install.sh`, `scripts/launch_host_node.sh` and both `install.ps1` copies pointing at the old layout. **Nobody could install a node on macOS or Linux, and CI was green over it for two days**, because the only installer check was `install.sh --dry-run` and every step of that script returns early in dry-run mode *after printing what it would do*. Windows was worse than broken: `install.ps1` found no `pyproject.toml` at the repo root, fell through to its clone branch, and installed the **archived pre-monorepo repo** — no error, just a node frozen before 1.4, 1.6, 2.1, 2.3 and 2.4. A second `install.ps1` under `packages/node/` had drifted into never generating `NODE_NETWORK_AUTH_TOKEN`, which the control API fails closed without (0.1), so that copy produced a node serving nothing; deleted. The fix that matters is not the paths but `scripts/verify_install.sh`, a gate step that runs the installer for real against a throwaway copy and asserts the result imports — **its first run immediately found a third bug** the dry-run never could: `packages/node` imported `structlog` and `httpx` without declaring them, resolving only because the shared dev venv has both. See `specs/installer-actually-installs.md`. | **done** | — |
| 2.7 | **Authenticate the Zenoh mesh ingress.** Supersedes 2.2 ("rotate `TELEMETRY_SECRET_KEY`"), which closes nothing. All three mesh inputs were forgeable by anyone who could reach the public bootstrap router: telemetry signed with a key whose default is a constant published here; heartbeats accepted as **plain unsigned JSON**; and — the worst — liveliness, where a DELETE took the node id from a key expression *the publisher chose* and called `unregister_node`, so **anyone could evict any host**. Now every message that changes registry state is an AES-256-GCM envelope keyed on that node's own `NODE_NETWORK_AUTH_TOKEN`, which the installer already generates per install and the Scheduler already stores at registration — closing the insider case a fleet-wide secret never could. Liveliness stops mutating state entirely: an unauthenticated signal may accelerate a check, never perform a write. **Absorbed the core of 2.5**, because removing the deathrattle's write without a time-based replacement would have traded an eviction hole for dead hosts advertised forever. See `specs/authenticated-mesh-ingress.md`. | **done** | 0.1 |

### Stage 3 — A stranger can actually use it

| # | Feature | Status | Depends on |
|---|---------|--------|-----------|
| 3.1 | **DONE.** `POST /v1/credentials` issues an RS256 JWT carrying the `tenant_id` claim the gateway requires and a `kid` so C4's rotation applies. Guarded by the **fleet credential, not by a JWT** — a JWT-guarded issuance endpoint lets any holder mint tokens for any tenant, which is privilege escalation dressed as a feature, and there is a test asserting a valid requester token cannot mint another. Deliberately **not self-service**: under D1/D4 this is invite-only, and issuing a credential is the human decision admission control exists to be. **There is no revocation**, because JWTs are stateless and adding one would mean a lookup on every request; the mitigations are a server-enforced TTL cap (asking for a decade gets 30 days) and key rotation as the blunt instrument. Said plainly in `docs/ACCEPTABLE_USE.md` rather than implying a revoke button exists. | **done** | 2.1 |
| 3.2 | **DONE, and the framing in this line is now wrong.** D2 cut payouts, so metering is *not* a prerequisite for billing — it exists for the three things that survived that decision: a host seeing what their machine did, an operator investigating abuse, and fair quota. **`UsageRecord` cannot hold prompt or completion text**, enforced by `extra="forbid"` on a closed model with no free-text field plus `tests/test_metering_privacy.py`, which also inverts the check (every string field must be a known identifier) so a future field named `note` fails too. That is the one part of D3's data-protection position that is a property of the code rather than of the deployment. Failed dispatches are recorded with `succeeded=False` and credit nobody. | **done** | 3.1 |
| 3.3 | **DONE.** The ledger was instantiated but **had no caller** — `record_host_contribution` was unit-tested and never invoked by the running application, which is why hosts accrued nothing. Now called on every successful completion, streaming and non-streaming. Streaming needed a `finally` around the generator, because the response has already started and there is no return statement to hang accounting on; without it the default path for any chat UI would have been invisible to both the meter and the ledger. Metering failure is non-fatal — a broken accounting system must not turn a completion the requester already received into a 500. **Credits are contributed, not earned** (D2). | **done** | 3.2 |
| 3.4 | **DONE.** The dashboard now shows what the host's machine served and what it **contributed**, reading `GET /api/usage?node=`. The word is *contributed*, never *earned* — D2 cut redemption, and `formatCredits` is a named export with a test asserting no currency symbol, because the language IS the product decision. Two other things the panel refuses to blur: an unreachable Scheduler renders as "unavailable", **not** as zero contributed, and a node that has served nothing shows `—` for its failure rate rather than a healthy-looking 0%. Totals are labelled as a window, since they come from a bounded tail. | **done** | 3.3 |
| 3.5 | **DONE.** `install.sh` now writes `packages/website/.env.local` with the **same** `NODE_AUTH_TOKEN` it just generated for the node, so the dashboard credential is never hand-copied between two files. Proved by running the real installer against a throwaway copy and comparing the two files — a dry-run cannot show that two files agree (2.8). Also fixed the requester half: the playground called its JWT field *"Optional custom RS256 Bearer JWT"*, which is false — the gateway has always required one and since C4 an unconfigured Scheduler refuses everyone. It now says **Required** and names where to get one. Found on the way: `public-intelligence-node` was a **tracked, dangling** symlink to `Node/.venv/`, broken in every fresh clone since the monorepo migration; it is a build artifact and is now ignored. | **done** | 1.1 |
| 3.6 | **DONE.** The `docs/` half was N2; this is the **website**, which was still the loudest source of the claim. Its landing page said *"The core distributed infrastructure is realized"* — the exact sentence pattern this project audits itself for — and led with "decentralized AI infrastructure", which D5 retired because the coordinator is a single point of trust. Both replaced, and the milestone block now names what is **not** true: no node on a separate machine has ever served a request. `docs/OPERATING.md` and `docs/ACCEPTABLE_USE.md` ship the operator-facing half, including the gaps — invite codes and D1's canary are decided and unimplemented, and the node writes generated completions to disk with no retention policy. | **done** | — |

### Stage 4 — Confidence to leave it running

| # | Feature | Status | Depends on |
|---|---------|--------|-----------|
| 4.1 | **DONE (proxies), and it found a live credential bug.** 16 vitest tests across the three proxy routes. The chat proxy's fallback branch sent `SCHEDULER_NETWORK_AUTH_TOKEN` — the **fleet shared secret**, the `X-Network-Auth-Token` value — as `Authorization: Bearer`. The gateway wants an RS256 JWT, so it could never have authenticated anything, and while failing it put a fleet-wide credential in an Authorization header on every unauthenticated request. Two credentials with two trust levels had one name; the fallback is now `SCHEDULER_PLAYGROUND_JWT`, and the caller's own header wins so a configured fallback cannot silently collapse every tenant onto the operator. **Still open:** the playground component and its SSE parsing are covered by nothing. | **partial** | — |
| 4.2 | **PARTIAL — aggregation done, alerting deliberately not.** `GET /metrics` reports request counts, token totals, per-node distribution and the **failure ratio** an operator actually watches, so something other than CI can notice breakage. JSON rather than Prometheus text format on purpose: an exposition endpoint implies a scrape contract (naming, label cardinality, HELP/TYPE) and getting that subtly wrong is harder to notice than not having it; adopting it later is a serialiser change. **Alerting is not here and is not pretended** — something outside the process has to poll and decide. Every counter is labelled as windowed, because a figure read as all-time that silently resets when the buffer wraps is worse than no figure. | **partial** | 2.1 |
| 4.3 | **DONE — tested end-to-end, and the behaviour was already right.** Seven tests covering an empty fleet, a model nobody hosts, a node refusing, Ollama unreachable, a node dying mid-stream, and the rate limit. Every one passed on first run, which is the honest outcome to report: 4.3 said "partly handled, never tested", and the gap was the verification, not the code. Mutation-checked so they are not vacuous — substituting a different model when the requested one is absent, and swallowing a mid-stream failure into a clean `[DONE]`, both fail. Those two are the ones that matter: they are the failure modes that would return something **plausible** rather than something wrong. | **done** | 1.5 |

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
