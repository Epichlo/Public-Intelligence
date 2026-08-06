# Spec: Scheduler persistence (ROADMAP 2.1)

## What this does

The Scheduler keeps everything it knows in Python dicts that die with the
process. Restarting it — a Render redeploy, a crash, `Ctrl-C` — loses every
registered node, every per-node credential, and every credit balance. This adds a
durable store behind the `NodeRegistry` and the `CreditLedger` so that state
survives a restart, and the Scheduler comes back knowing its fleet instead of
waiting to be re-told.

Persistence is **opt-in**: with no `SCHEDULER_DATABASE_PATH` set, behaviour is
byte-for-byte what it is today. That is deliberate — see "The Render caveat".

## What actually breaks today

`NodeRegistry.__init__` (`registry/node_registry.py:23`) builds six dicts and a
set. `CreditLedger.__init__` (`core/credit_ledger.py:36`) builds one. Nothing
writes any of it anywhere. `main.py:82` constructs the registry inside
`create_app()`, so every process starts empty.

Two consequences, of very different severity:

**The fleet is reconstructible; the balances are not.** Since 1.6 a node whose
heartbeat 404s treats that as "the Scheduler has forgotten me" and re-registers
with full detail on a jittered backoff. So a restarted Scheduler *does* recover
its node list on its own, within roughly `registration_retry_max_seconds`. A
credit balance has no such source: no node can re-tell the Scheduler what it
earned, because the node never knew. **Losing the ledger is unrecoverable data
loss; losing the registry is a recovery window.** Both are fixed here, but they
are not the same problem and the spec should not pretend they are.

**The recovery window is not nothing.** Until a node re-registers, it is invisible
to matchmaking, so `/v1/chat/completions` answers "no node has this model" for
work the fleet could serve. Restoring the registry closes that window to zero for
the HTTP dispatch path, and to one heartbeat interval for the mesh path.

The roadmap line for 2.1 was written before 1.6 existed and says the registry loss
is the headline. After 1.6 the ledger is. Recording that here rather than
inheriting a stale framing.

## Design decisions, and why

**Write-through, not read-through.** The in-memory dicts stay exactly as they are
and remain the only read path; mutations additionally write to the store; startup
loads the store into the dicts. The alternative — querying the database on reads —
would put an I/O call on the hot path of every dispatch and every `filter_nodes`
call (`matchmaker.py:41` reaches straight into `registry._heartbeats`), and would
mean rewriting the matchmaker, the dispatcher, and every test that constructs a
registry. Write-through leaves all of that untouched.

**The store is injected and defaults to absent.** `NodeRegistry()` with no store
is today's class, unchanged, so of the existing 227 scheduler tests only the five
that call a method whose *signature* changed needed editing — none needed editing
because behaviour changed. `create_app()` with no argument builds no store — it
deliberately does **not** read `get_settings()` for this — so no ambient `.env`
value can turn persistence on underneath a test suite. The deployed app gets its
store from `main.py`'s module scope, which is the one place settings are consulted.

**Not everything in the registry should be restored.** Deciding this per field,
rather than persisting the whole object:

| State | Persisted | Why |
|---|---|---|
| `_nodes` | yes | The fleet. What this feature is for. |
| `_node_tokens` | yes | Without the credential the Scheduler cannot call a node back — its `/infer` fails closed. Restoring nodes without tokens would restore a fleet the Scheduler 401s against. |
| `_heartbeats` | **no** | A heartbeat is a *live* reading. Restoring a stale one presents an old VRAM/queue figure as current. `matchmaker.py:42` already falls back to the node's registered `gpu.vram_available_gb` when there is no heartbeat, which is a static hardware fact rather than an expired measurement — correct-on-restart beats stale-and-confident. |
| `_mesh_nodes` | **no** | This is *evidence of a live Zenoh session*, and the session does not survive the process. Restoring it makes dispatch prefer the mesh for a node with no queryable declared, so every request pays `mesh_inference_first_reply_timeout_seconds` (5s) before falling back to HTTP. The node re-asserts it for free on its next heartbeat. |
| `_dampeners` | **no** | Transient scheduling backpressure; `update_heartbeat` resets it to 0.0 on the next heartbeat regardless. |
| `_telemetry` | **no** | Live metric, same argument as heartbeats. |

The rule the table encodes: **persist facts, not observations.** A node's hardware
and its credential are facts about it. Its queue depth and its mesh presence are
observations that were true at a moment which has passed.

**`set_node_token` becomes async.** It has one production caller
(`api/nodes.py:76`) and is not on a hot path — `get_node_token` is, and stays
synchronous and lock-free as documented. Making the setter async is what lets a
token rotation persist: `register_node` records the token *before* attempting
registration precisely so a re-registering node with a new token refreshes it even
on the 409 path, and that refresh has to reach the store or the whole reason for
the ordering is lost across a restart.

**Tokens get their own table.** They are written before the node row exists (see
above) and must outlive a 409, so they cannot be a column on `nodes`. The schema
ends up mirroring the reason they are held outside the `Node` model in memory: a
token is not part of the node's public description.

**Nodes stored as JSON, accounts as columns.** `Node` is nested (`GPUInfo`, a
`list[str]`) and its shape changes as the roadmap moves; exploding it into columns
would mean a migration per field and would duplicate validation pydantic already
does. `CreditAccount` is four flat scalars and it is *money* — real columns mean
an operator can audit balances with one `sqlite3` query instead of parsing JSON
out of a blob.

**A row that fails to load costs one node, not the whole Scheduler.** If a stored
`Node` no longer validates — schema drift, a truncated write — it is logged and
skipped, and startup continues. The opposite (refuse to start) turns one bad row
into a total outage, and the node it belonged to would have re-registered anyway.

**SQLite calls are synchronous and not offloaded to a thread.** Writes are
single-row upserts of a few hundred bytes with `journal_mode=WAL` and
`synchronous=NORMAL`, so a commit does not fsync. Wrapping them in
`asyncio.to_thread` would hold the registry's `asyncio.Lock` across a thread hop —
more contention for the same work. This is a judgement about expected volume (tens
of nodes, a heartbeat every few seconds), **not a measurement under load**; if the
fleet grows by orders of magnitude this is the assumption to revisit.

**The interface is a `Protocol`, and it is async.** Nothing in it depends on
SQLite. A Postgres backend — which is what an operator on a real Render plan
should use — implements the same nine methods without the registry or the ledger
changing. Async now, so that swap does not have to change every call site later.

### The Render caveat

Render's free tier has an **ephemeral filesystem**. A SQLite file there survives a
process restart inside the same container and is **wiped by every redeploy**. So
persistence defaulting to on would produce exactly the failure this repo keeps
running into: a thing that appears to work and silently does not. It defaults to
off, `.env.example` states the caveat where an operator will read it, and the
Scheduler logs `persistence_enabled` with the resolved path at startup so the
answer is in the logs rather than in prose that can go stale.

## Done looks like

- [x] `SCHEDULER_DATABASE_PATH` unset ⇒ `create_app()` builds no store and the
      registry behaves exactly as today. Covered by a test asserting
      `registry._store is None` and that register/unregister still work.
- [x] A `NodeRegistry` with a store, given a registered node, is reconstructed by
      a **second, independent** `NodeRegistry` pointed at the same database —
      same `node_id`, same `gpu`, same `available_models`. Covered by a test.
- [x] The per-node auth token survives that reconstruction, and a token rotated on
      a 409 re-registration is the one that survives. Two tests.
- [x] `_mesh_nodes`, `_heartbeats`, `_dampeners`, and `_telemetry` are **not**
      restored: after reload, `is_mesh_reachable` is False and `get_heartbeat` is
      None for a node that had both before. Covered by a test.
- [x] `unregister` removes the node *and its token* from the database, so it does
      not come back on the next start. Covered by a test.
- [x] `set_available_models` persists, so a catalogue refresh (1.4) is not lost by
      a restart. Covered by a test.
- [x] A `CreditLedger` with a store reloads earned and consumed balances exactly,
      including a float that does not round-trip through a naive format. Covered
      by a test.
- [x] A stored node row that no longer validates is skipped with a log, the
      remaining rows load, and `load()` does not raise. Covered by a test.
- [x] Two registries pointed at *different* database files do not see each other's
      nodes. Covered by a test.
- [x] The full restart is exercised end to end through the API: register a node
      over HTTP against one app, build a second app on the same database, and
      `GET /nodes/{id}` returns it. Covered by a test.
- [x] Startup logs `persistence_enabled=true|false` and, when true, the path.
- [x] `./scripts/verify.sh` passes.

## Out of scope

- **Persisting batch jobs.** `_BATCH_TASKS` (`api/batch.py:12`) is lost on
  restart, and the roadmap line names it. It is deliberately left in memory
  until **2.4** lands: `POST /v1/batch` has no auth dependency at all, so giving
  it a database converts an unauthenticated unbounded-memory growth path into an
  unauthenticated unbounded-**disk** growth path. Ordering, not omission — 2.1's
  roadmap entry is updated to say so, and 2.4 gains a note that batch persistence
  follows it. (Independently, `submit_batch_job` fabricates its results and
  dispatches nothing, so what would be made durable today is not a record of any
  work.)
- **Making the ledger earn anything.** `CreditLedger` gets a store and is
  instantiated on `app.state`, so its balances are durable and are loaded at
  startup. **Nothing credits it.** Accrual on real usage is 3.2/3.3. A durable
  ledger of zeroes is still a durable ledger, and it is what 3.2 needs to exist
  before it can write to it.
- **A Postgres backend.** The `Protocol` exists so one can be added; it is not
  added here. Anyone deploying where durability actually matters needs it.
- **Multi-process or multi-instance safety.** One Scheduler process owns the
  database file. SQLite's WAL mode tolerates concurrent readers but nothing here
  coordinates two Schedulers writing the same file, and the consensus engine
  (`core/consensus.py`) is explicitly not in v1.
- **Migrations.** The schema is created with `CREATE TABLE IF NOT EXISTS` and a
  recorded version. Changing it later needs a migration path that does not exist
  yet; a version mismatch is logged loudly rather than silently coerced.
- **Encrypting tokens at rest.** The database holds per-node credentials in
  plaintext, exactly as the process memory does today. File permissions are the
  control. Saying so here rather than leaving a reader to assume otherwise.
- **Restoring `Heartbeat`/telemetry state.** Deliberate, with reasons, in the
  table above — a known and intended gap, not an oversight.

## Verification

```
./scripts/verify.sh
.venv/bin/python -m pytest packages/scheduler/tests/test_persistence.py -q
.venv/bin/python -m pytest packages/scheduler/tests/test_registry -q
grep -rn "SCHEDULER_DATABASE_PATH" .env.example packages/scheduler/src
```

## Notes / open questions

- Duplicate-module check: `NodeRegistry` and `CreditLedger` exist only in
  `packages/scheduler`. Neither is one of the six duplicated pairs, and the new
  package is named `scheduler/persistence/` rather than `scheduler/storage/`
  specifically so it is not mistaken for the artifact store that already exists in
  three copies at `src/shared/storage/`. Confirmed before writing this.
- Open: whether a restored node should be treated as unverified until its first
  heartbeat — i.e. loaded but excluded from dispatch for one interval. Argument
  for: a node that died while the Scheduler was down is now advertised as live.
  Argument against: the existing stale-eviction path (2.5) is what is supposed to
  handle exactly that, and duplicating it here would give two mechanisms with
  different timeouts. Left alone; noted so the interaction with 2.5 is a decision
  someone made rather than one nobody noticed.
- The `updated_at` on `CreditAccount` is `time.time()`, a float epoch. Stored as
  REAL, so it round-trips without formatting.
