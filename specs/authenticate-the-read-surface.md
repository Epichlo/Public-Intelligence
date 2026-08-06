# Spec: Authenticate the read surface (ROADMAP 2.6)

## What this does

Most of the Scheduler's API answers anyone who can reach it. This puts the
fleet-describing endpoints behind the same credential their siblings already
require, and states — rather than leaves implicit — which endpoints stay public
and why.

## What actually breaks today

Enumerated from the routers, not assumed. Every route below takes **no auth
dependency at all**:

| Route | What it hands out |
|---|---|
| `GET /nodes` | Every node's hostname, IP, region, GPU model, VRAM, CPU count, RAM, and model catalogue |
| `GET /nodes/{id}` | The same, for one node |
| `GET /nodes/telemetry` | **Live decrypted metrics for the entire fleet** |
| `GET /nodes/{id}/telemetry` | The same, for one node |
| `GET /status` | Per-node snapshots: hostname, region, status, queue depth, CPU, GPU, VRAM |
| `GET /v1/models`, `GET /v1/models/{id}` | Model names aggregated across the fleet |
| `GET /health`, `GET /health/ready` | Version, environment, uptime |
| ~~`POST /v1/webhooks/github`~~ | **Not mounted — see the correction below.** |

**The roadmap line for 2.6 named five of these and missed the two that matter
most.** `/nodes/telemetry` returns the whole `_telemetry` dict — the live per-node
metrics that ROADMAP 2.7 just spent a protocol change protecting *in transit*.
Authenticating the mesh so only a node can report its own metrics, while serving
those same metrics to anyone over HTTP, would have been half a fix.

**`POST /v1/webhooks/github` — CORRECTED.** This spec first claimed it was a live
unauthenticated write path. **It is not: `create_app` never includes the webhooks
router, so those paths 404.** That surfaced only because the test written from this
spec asserted 401 and got 404. The claim is corrected here rather than quietly
dropped, because a spec that overstated a vulnerability is the same defect as one
that understated it.

It is guarded anyway, at the router level, so that mounting it later is a one-line
change that does not also open an anonymous POST. Worth noting for whoever mounts
it: `AutonomousOrchestrator.execute_mission` is a **pure stub** — it formats strings
and returns, running no code and opening no PR.

It does, however, return `verification_passed=True` and a body reading "Closed-loop
tri-factor verification (pytest, ruff, mypy) passed cleanly" for work it never did.
That is the exact class of claim this repo's own docs exist to stamp out. Fixing
the lie is **not** in this change; it is recorded below.

## Design decisions, and why

**The fleet endpoints take `verify_auth_token`, the same dependency their siblings
already carry.** `POST /nodes/register`, `PUT /nodes/{id}/models` and
`DELETE /nodes/{id}` are already guarded by it. A router where three routes are
protected and two are not is not a policy, it is an oversight with a pattern.

**`/health` and `/health/ready` stay public.** They are liveness and readiness
probes. Render calls them without credentials, and a health check that needs a
secret is a health check that reports "unhealthy" when the secret is wrong. They
return a version, an environment name and an uptime — no fleet data.

**`/v1/models` and `/v1/models/{id}` stay public, deliberately.** This is a
judgement, so it is stated as one rather than buried. The product is a marketplace:
a developer deciding whether to obtain a credential should be able to see what the
network can serve. What these return is a *set of model names*, aggregated across
the fleet — not which node has what, not hardware, not addresses. That is a
materially smaller disclosure than `/nodes`, which is why the two are treated
differently.

I am deliberately **not** citing what the real OpenAI API does here. An earlier
spec of mine asserted in passing that model discovery is public there; I did not
verify it, and it should not be load-bearing for this decision either way.

**`POST /v1/webhooks/github` gets `verify_auth_token`, not a GitHub HMAC
signature.** Signature verification (`X-Hub-Signature-256`) is what a real GitHub
webhook should use, and it needs a shared webhook secret that nothing in this repo
provisions. The network token is what exists today and closes the endpoint now; the
proper fix is recorded as a follow-up rather than half-built here.

**The dashboard's proxy gains the credential it was missing.**
`packages/website/src/app/api/telemetry/all/route.ts` calls `/nodes/telemetry` with
no headers. `api/status/route.ts` already sends `X-Network-Auth-Token` from
`SCHEDULER_NETWORK_AUTH_TOKEN`, so the pattern exists and the telemetry proxy is
simply the one that never got it.

## Done looks like

- [x] `GET /nodes`, `GET /nodes/{id}`, `GET /nodes/telemetry`,
      `GET /nodes/{id}/telemetry` and `GET /status` return **401** without a
      credential and 200 with one. One test per route, asserting both.
- [x] The webhooks router carries `verify_auth_token`, asserted on the router
      object because the router is **not mounted** and there is no path to call.
      (This box originally read "returns 401 without a credential"; it was
      corrected when the test returned 404 and revealed the router is unmounted.)
- [x] `GET /health` and `GET /health/ready` still answer **200 with no
      credential** — a probe that needs a secret is broken. Covered by a test.
- [x] `GET /v1/models` still answers 200 with no credential, and a test says in
      its docstring that this is a decision, not an omission.
- [x] A test enumerates the app's routes and fails if a **new** unauthenticated
      route appears that is not on an explicit allowlist — so the next one is
      caught when it is added, not two roadmap items later.
- [x] The website's telemetry proxy sends `X-Network-Auth-Token`.
- [x] `./scripts/verify.sh` passes.

## Out of scope

- **The orchestrator's false claim.** `execute_mission` returns
  `verification_passed=True` and prose asserting pytest/ruff/mypy "passed cleanly"
  for a stub that runs none of them. Authenticating the endpoint does not make the
  response honest. Recorded as ROADMAP 2.10, along with the prior question of
  whether the webhook and orchestrator should be mounted in v1 at all, given the
  autonomous orchestrator is on the roadmap's "deliberately not in v1" list.
- **Real GitHub webhook signature verification.** Needs a provisioned secret.
- **Per-tenant scoping of node data.** Every holder of the network token sees the
  whole fleet. That is the correct granularity while the token is fleet-wide;
  finer-grained access belongs with requester credentials (3.1).
- **Website tests.** `packages/website` has no test harness — no runner, no test
  files. The proxy change is therefore **unverified by any automated test**, and
  that is stated here rather than glossed. It is ROADMAP 4.1.
- **Rate limiting the now-authenticated reads.** Unchanged.

## Verification

```
./scripts/verify.sh
.venv/bin/python -m pytest packages/scheduler/tests/test_read_surface_auth.py -q
grep -rn "X-Network-Auth-Token" packages/website/src/app/api/telemetry/all/route.ts
```

## Notes / open questions

- Duplicate-module check: this adds no module. It adds a dependency to existing
  routes and one header to one TypeScript file.
- The route-inventory test is the part with lasting value. Every item in the table
  above existed because a route was added without anyone asking what guards it, and
  a list in a spec cannot notice the next one.
- Open: `GET /nodes` is what the public dashboard would need if it ever showed a
  live network map without a credential. If that becomes a product requirement, the
  answer is a deliberately narrowed public projection (counts, aggregate capacity),
  not re-opening the full record.
