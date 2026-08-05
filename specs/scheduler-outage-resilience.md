# Spec: Node survives a Scheduler outage (ROADMAP 1.6)

## What this does

If the Scheduler is unreachable when a node boots, the node process dies. Today
that is a hard failure: uvicorn prints "Application startup failed. Exiting." and
the host is left with nothing running. After this change the node starts anyway,
serves its own local API, and retries registration in the background with backoff
until the Scheduler answers — and if it is later evicted while the Scheduler is
down, it re-registers itself instead of heartbeating into the void forever.

## What actually breaks today

`main.py:29` calls `runtime.start()` inside the FastAPI lifespan.
`runtime.start()` reaches `await self.scheduler_client.register(node_info)`
(`runtime.py:128`), which raises `SchedulerError` on any connection error,
timeout, or non-2xx. The outer `except Exception` at `runtime.py:174` sets
`registration_status = "failed"` and **re-raises**. Nothing above it catches, so
the exception leaves the lifespan and uvicorn aborts startup.

The consequence is scoped by how the node is deployed: `install.sh` sets
`NODE_SCHEDULER_URL` to a hosted Scheduler. A Render free-tier cold start takes
tens of seconds, and a host who boots their machine in that window gets a dead
process with no retry and no supervision.

**The same defect exists after boot, and is more likely to fire.** Once
registered, `_heartbeat_loop` posts to `/heartbeat`, which 404s for a node the
registry does not know. The Scheduler holds its registry in an in-memory dict
(ROADMAP 2.1), so *every Scheduler restart* makes *every* node's heartbeat 404
forever. The node logs the error each interval and never re-registers. It is
invisible to matchmaking until someone restarts it by hand.

The roadmap entry says "at boot", which is where it was found. Treating only the
boot case would leave a node that survives an outage during its first second and
dies permanently to one at minute five, using the same broken assumption. Both
are fixed here; that is a deliberate widening of the roadmap line, recorded here
rather than discovered later.

## Design decisions, and why

**Only `SchedulerError` is survivable.** Everything else still propagates and
still kills startup. A `ValidationError` from building `NodeInfo`, or a
`TypeError` in a probe, is a bug in this node — starting degraded would hide it.
The distinction is the point: "the Scheduler is down" is an expected environmental
state, "this code is wrong" is not.

**`SchedulerError` grows a `status_code`.** The client already inspects
`"409" in str(e)` to detect an existing registration — matching on the text of an
error message, which breaks the moment the message is reworded. Distinguishing a
404 heartbeat (re-register) from a 500 (retry, do not re-register) needs the same
information, so the status code becomes a real attribute and the string match goes
away.

**Full jitter on the backoff, not plain exponential.** The scenario that produces
this is a Scheduler that was down and came back — which means every node retries
at once. Plain exponential backoff synchronises them into a thundering herd
against a service that just started. Sleep is `random.uniform(0, interval)` with
`interval` doubling to a cap. (`random` here is scheduling jitter, not
cryptographic material — unrelated to the misuse this repo had in `telemetry.py`,
where a random number was published as a CPU measurement.)

**The heartbeat and catalogue-refresh loops do not run while unregistered.** Both
would post to endpoints that 404 for an unknown node, once per interval, forever.
Gating them on `registration_status == "registered"` keeps the logs meaningful.

**A 404 heartbeat sets the state back to pending and re-arms the retry loop**,
rather than re-registering inline. One path owns registration, so backoff and
jitter apply to a mid-life recovery exactly as they do at boot.

**Ordering inside `start()` is unchanged.** Registration failure stops being
fatal, so the Zenoh client, telemetry emitter, mesh inference server, and worker
loop all start as they already did. The node joins the mesh whether or not the
Scheduler knows about it, which is what lets the Scheduler observe it as
mesh-reachable once registration lands.

## Done looks like

- [x] `Runtime.start()` completes with `is_running is True` when
      `scheduler_client.register` raises `SchedulerError`, and leaves
      `registration_status == "pending"`. Covered by a test.
- [x] `Runtime.start()` still raises, and still leaves `is_running is False`, for
      any non-`SchedulerError` exception. Covered by a test.
- [x] The Zenoh client, mesh inference server, worker loop, and both periodic
      tasks are running after a degraded start. Covered by a test.
- [x] A background retry task re-attempts registration with exponential backoff
      and full jitter, capped at `Settings.registration_retry_max_seconds`
      (default 60), and stops as soon as it succeeds. Covered by a test that
      asserts the sleeps grow and stay within the cap.
- [x] On a late registration success the catalogue is reconciled the same way
      `start()` does it — fresh create records `advertised_models`, a 409 pushes.
      Covered by a test.
- [x] `stop()` cancels the retry task; `retry_task is None` afterwards.
- [x] `SchedulerError` carries `status_code`, and `register` decides "already
      registered" from `status_code == 409` rather than `"409" in str(e)`.
- [x] A heartbeat that fails with 404 sets `registration_status` back to
      `"pending"` and re-arms the retry loop; a 500 does not. Covered by two tests.
- [x] The heartbeat and model-refresh loops send nothing while unregistered.
      Covered by a test.
- [x] `GET /health/ready` reports `scheduler_registered: false` and 503 during a
      degraded start, and returns 200 once registration lands. Two tests.
- [x] The node's own local API still serves while unregistered — `/health` reports
      healthy and `/models` returns the catalogue. Covered by a test.
      (This box originally said `/infer`; it was reworded to name the endpoints
      actually exercised rather than one that is not.)
- [x] `./scripts/verify.sh` passes.

## Out of scope

- **Making the Scheduler durable.** It still loses every node on restart; that is
  2.1. This change makes nodes recover from that, which is not the same as it not
  happening.
- **Retrying `unregister` on shutdown.** `stop()` already suppresses the failure,
  and a node going away while the Scheduler is down is corrected by stale
  eviction (2.5).
- **Supervision / auto-restart of the node process.** Out of scope here; a node
  that fails for a real reason should still exit and be restarted by whatever runs
  it.
- **Backoff on the heartbeat interval itself.** Heartbeats keep their fixed
  interval. Only registration backs off.
- **A bound on retry attempts.** The loop retries for the life of the process. A
  node whose Scheduler is down for a day should join when it returns, not give up.

## Verification

```
./scripts/verify.sh
.venv/bin/python -m pytest packages/node/tests/test_scheduler_outage.py -q
.venv/bin/python -m pytest packages/node/tests/test_scheduler_client.py -q
grep -n '"409" in str' packages/node/src/node/clients/scheduler.py   # expect no hits
```

## Notes / open questions

- The cap of 60s means a node discovers a recovered Scheduler within a minute in
  the worst case, and much sooner with jitter. That is well inside the Scheduler's
  own stale-eviction window, so a recovering node is not evicted mid-retry.
- `registration_status` gains one value, `"pending"`. `inference.py:189` compares
  against `"registered"` and so already treats anything else as not-ready; no
  change needed there.
- Duplicate-module check: `Runtime` and `SchedulerClient` exist only in
  `packages/node`. Neither is one of the six duplicated pairs. Confirmed before
  writing this.
