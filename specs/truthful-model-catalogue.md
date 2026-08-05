# Spec: Model catalogue is truthful (ROADMAP 1.4)

## What this does

A node tells the Scheduler which models it can serve exactly once — during
`Runtime.start()` — and then never mentions models again. If the host runs
`ollama pull` the network never learns about the new model, and if the host runs
`ollama rm` the Scheduler keeps advertising and routing to a model that is gone.
After this change the node re-checks Ollama on an interval and pushes the
catalogue to the Scheduler whenever it has actually changed, so `GET /v1/models`
and matchmaking describe what the fleet can really serve right now.

## The three failure modes this closes

Each was read out of the code, not inferred:

1. **A pulled model is unroutable.** `runtime.py:82` calls
   `ollama_client.list_models()` once inside `start()`. There is no other caller
   in the service. `matchmaker.py:35` and `scheduler/algorithm.py:44` both skip a
   node whose `available_models` lacks the requested name, so a freshly pulled
   model is invisible until the node process restarts.

2. **A deleted model is still advertised, and requests routed to it fail.**
   Same staleness in the other direction. `openai.py:586` builds `GET /v1/models`
   from the union of every node's `available_models`, so the public catalogue
   lists it; the matchmaker then picks that node and its Ollama answers 404.

3. **Restarting the node does not fix either one.** `local_register`
   (`node_registry.py:101`) raises when the `node_id` is already present, so
   `POST /nodes/register` returns 409, and `SchedulerClient.register`
   (`clients/scheduler.py:129`) *swallows* that 409 and logs "Node already
   registered". The node then heartbeats normally while the Scheduler holds the
   catalogue from a previous process. Heartbeats carry no model list — there is
   no field for one — so nothing ever corrects it.

Separately: **`Settings.hosted_models` is a lying knob.** It is declared
(`configuration.py:77`), unit-tested six ways, and advertised to operators in
`packages/node/.env.example:15` and `packages/node/examples/demo.md:28` as the
list of models this node hosts. It does not control what the node advertises —
nothing on the registration or heartbeat path reads it. Its one production read
is `runtime.py:372`, where `hosted_models[0]` supplies a `model_id` label to a
`PipelineStage` inside the split-inference stage listener: a path whose backend
is always `EchoBackend` and which is explicitly cut from v1. So an operator who
sets `NODE_HOSTED_MODELS` changes a string on a code path that does not run, and
does not change what their node advertises.

## Design decisions, and why

**Refresh is pushed by the node, not polled by the Scheduler.** The Scheduler
cannot dial most nodes (that is what 1.1 was about). The node already holds an
outbound connection and already runs a periodic loop; a second one is cheap.

**A dedicated `PUT /nodes/{node_id}/models`, not an upsert on
`/nodes/register`.** Registration stays "create", and its 409 keeps meaning what
it means today. The narrow endpoint also limits what a node can restate at
runtime to the one thing that genuinely changes while the process is alive: its
model list. Hardware does not change mid-process, and letting a node re-assert
`gpu`/`ram_total_gb` through a refresh path would widen what 1.2 deliberately
made measured rather than claimed.

**The push happens only when the catalogue differs from what was last
advertised.** The list is near-constant. Sending it every heartbeat would put a
list on the wire ~2,880 times a day per node to communicate something that
changes a few times a year.

**An Ollama failure during refresh must not clear the catalogue.** If
`list_models()` raises, the previously advertised list is kept and the failure
logged. Treating "I cannot reach Ollama" as "I have no models" would unadvertise
the whole node on a transient blip, then re-advertise seconds later — flapping
the fleet catalogue and evicting the node from matchmaking for no reason. This
is the opposite of the startup path, where advertising nothing is correct
because nothing has been advertised yet.

**A 409 at registration triggers an immediate catalogue push.** That is the
signal that the Scheduler holds a record this process did not write, so its
catalogue is by definition from an older process and must be corrected now
rather than at the first interval.

**`hosted_models` is deleted, not wired up.** The truth source is what Ollama has
pulled. A config list is a *claim*, which is the exact class of untruth 1.2 and
1.3 removed from hardware and heartbeats. Deleting it costs one line in the
split-inference stage listener, which falls back to the same `"default"` label it
already uses whenever the setting is unset — i.e. by default, today.

## Done looks like

- [x] `Runtime` runs a model-refresh task alongside the heartbeat task; `stop()`
      cancels it. Interval from a new `Settings.model_refresh_interval_seconds`
      (default 60, validated `> 0` like `heartbeat_interval_seconds`).
- [x] The refresh pushes only on change: two consecutive refreshes returning the
      same model names produce exactly one HTTP call (the first, if any).
      Covered by a test asserting the call count.
- [x] `list_models()` raising during a refresh leaves the advertised catalogue
      unchanged and sends nothing. Covered by a test.
- [x] `SchedulerClient.register` returns whether the Scheduler *created* the
      record (`True`) or answered 409 (`False`), and `Runtime.start` pushes the
      catalogue immediately when it is `False`. Covered by a test.
- [x] `PUT /nodes/{node_id}/models` exists on the Scheduler, requires
      `verify_auth_token`, 404s for an unregistered node, and replaces that
      node's `available_models`. The read-modify-write happens inside
      `NodeRegistry`'s lock via a new `set_available_models`, not as a
      `get()`-then-`update()` pair across an await.
- [x] `GET /v1/models` reflects a pushed catalogue: pull-then-refresh makes a new
      model appear, rm-then-refresh makes it disappear. Covered by a Scheduler
      test driving the endpoint.
- [x] `tests/test_wire_contract.py` feeds the node's real catalogue-payload
      builder to the Scheduler's real request model, as it does for registration
      and heartbeat.
- [x] `Settings.hosted_models` is gone, along with its tests, its two lenient-list
      parsing hooks, its two documentation references, and its use in
      `examples/demo.py`. The split-stage listener keeps the `"default"` label it
      already produced for every node that had not set the variable.
- [x] `OllamaClient.list_models` no longer re-issues `show()` for a model whose
      digest it has already resolved, so the refresh loop does not re-run an N+1
      against Ollama every interval.
- [x] `./scripts/verify.sh` passes.

## Out of scope

- **Verifying that a node can actually serve what it advertises.** The Scheduler
  trusts the pushed list, exactly as it trusts the registration list today. A
  node can still lie; that is unchanged and is not what 1.4 is about.
- **Reacting to a model disappearing mid-request.** If Ollama loses a model
  between matchmaking and generation the request still fails. Graceful
  degradation is 4.3.
- **Event-driven refresh.** Ollama has no change-notification API, so this polls.
  The interval is the staleness bound: worst case `model_refresh_interval_seconds`
  of wrongness after a pull or rm.
- **Persisting the catalogue.** The Scheduler is still in-memory (2.1); a
  Scheduler restart loses every node, catalogue included.
- **`context_length` accuracy.** `list_models` still falls back to 2048 when
  `show()` gives nothing usable. Pre-existing, unchanged.

## Verification

```
./scripts/verify.sh
.venv/bin/python -m pytest packages/node/tests/test_model_catalogue_refresh.py -q
.venv/bin/python -m pytest packages/scheduler/tests/api/test_model_catalogue_update.py -q
.venv/bin/python -m pytest tests/test_wire_contract.py -q
grep -rn "hosted_models" packages/ | grep -v node_modules   # expect no hits
```

## Notes / open questions

- The default interval of 60s is a guess at the right trade between staleness and
  chatter. It is one HTTP call per node per minute *only when something changed*;
  the steady-state cost is one local `ollama list` per node per minute.
- `available_models` on the Scheduler's `Node` is `list[str]`, while the node
  carries `list[ModelInfo]` with size/family/context length. The push flattens to
  names, matching what registration already does. The richer metadata still never
  reaches the Scheduler — pre-existing, and out of scope here.
- Duplicate-module check: `ModelInfo` exists only in `packages/node`; there is no
  Scheduler twin to keep in step. Confirmed before writing this.
