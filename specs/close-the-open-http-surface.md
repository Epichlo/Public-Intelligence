# Spec: Close the open HTTP surface (ROADMAP 2.3 + 2.4)

## What this does

Two holes on the Scheduler's and Node's HTTP surface, fixed together because they
are the same shape — a door left open by a default nobody revisited.

**2.3** Both services send CORS headers that let *any* website make credentialed
cross-origin requests and read the responses. After this, cross-origin access is
off unless an operator names the origins.

**2.4** `POST /v1/batch` and `GET /v1/batch/{id}` have no authentication at all.
After this they require the same RS256 JWT the rest of the `/v1` gateway requires,
and a batch is readable only by the tenant that submitted it.

## What actually breaks today

### 2.3 — the roadmap's premise is wrong, and the truth is worse

ROADMAP 2.3 says the wildcard-plus-credentials combination is "rejected by browsers
and wrong in intent". The first half is false, and it matters: it describes a
config that fails **safe**, when the real one fails **open**.

Starlette does not send `Access-Control-Allow-Origin: *` when `allow_credentials`
is set. It reflects the requesting `Origin` back. Measured against the exact
current config (`starlette 1.3.1`, this session):

```
simple GET  -> {'access-control-allow-origin': 'https://evil.example',
                'access-control-allow-credentials': 'true'}
preflight   -> 200 {'access-control-allow-methods': 'DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT',
                'access-control-allow-credentials': 'true',
                'access-control-allow-origin': 'https://evil.example',
                'access-control-allow-headers': 'authorization'}
```

So it is not broken — it works, universally, for every origin that asks. Combined
with `allow_headers=["*"]`, any page on the internet can preflight and send an
`Authorization` header to either service and read the answer.

**What that actually costs, stated precisely.** These APIs authenticate with
`Authorization: Bearer` and `X-Network-Auth-Token` *headers*, not cookies, so a
hostile page has no victim credential to replay — this is not session riding. The
real exposure is the **unauthenticated** endpoints, which is most of the surface:
`GET /nodes`, `GET /nodes/{id}`, `GET /v1/models`, `GET /status` on the Scheduler,
and the Node's own API. A Scheduler on a private network or on `localhost` is
reachable from any page an operator visits, and reflected-origin CORS makes the
*response readable*. Without those headers the browser still sends the request but
the page cannot read the reply. That difference is the whole fix.

**Nothing legitimate uses it.** Every browser `fetch` in `packages/website` targets
a same-origin `/api/...` Next.js route, which calls the Scheduler and Node
**server-side** (`app/api/chat/completions/route.ts`, `api/models/route.ts`,
`api/status/route.ts`, `api/telemetry/all/route.ts`, `api/node/telemetry/route.ts`,
`api/node/control/route.ts`). Checked by grep across the whole app: there is no
cross-origin browser request to either service. Defaulting the allowlist to empty
therefore breaks nothing that exists.

### 2.4 — the batch endpoints have no dependency at all

`api/batch.py` declares its router with no `dependencies=` and neither route takes
an auth dependency, while its sibling `/v1/chat/completions` takes
`Depends(verify_jwt)`. Anyone who can reach the Scheduler can submit batches and
read every batch anyone else submitted, by id.

Two further facts found while reading it, both in scope because 2.4 is meaningless
without them:

- **There is no owner on a batch.** `_BATCH_TASKS[batch_id]` stores the response and
  nothing else. Adding authentication alone would give "any valid token reads every
  batch", which is not what 2.4 is for.
- **`_BATCH_TASKS` is a module-level global**, so every `create_app()` in one
  process shares it. That is a correctness bug independent of auth, and it is the
  specific thing `specs/scheduler-persistence.md` named as the reason batch
  persistence was deferred out of 2.1.

## Design decisions, and why

**Empty allowlist means the middleware is not installed at all**, rather than
installed with an empty list. No CORS headers is the honest expression of "no
cross-origin access"; an empty `allow_origins` still runs the middleware and still
answers preflights, which invites the reader to think something is configured.

**A configured origin list turns credentials back on, and `"*"` in it is a
startup error.** The trap this fix exists to remove is precisely `allow_origins`
containing `"*"` alongside credentials, and an operator setting
`SCHEDULER_CORS_ALLOW_ORIGINS=*` would walk straight back into it. A field
validator rejects it with a message naming the reflected-origin behaviour, so the
failure is at boot with an explanation rather than silent.

**Methods and headers become explicit lists, not `*`.** With an exact origin list a
method wildcard is far less dangerous, but re-introducing one leaves the next
reader unable to tell which was reasoned about. The header list is the three the
services actually accept: `Authorization`, `Content-Type`, `X-Network-Auth-Token`.

**Batch ownership keys on `tenant_id`, not `sub`.** That is the claim `verify_jwt`
already requires and the one `/v1/chat/completions` already scopes on, so batch
does not invent a second notion of identity.

**A batch belonging to another tenant answers 404, not 403.** 403 confirms the id
exists, which turns the endpoint into an oracle for enumerating other tenants'
batch ids. 404 is indistinguishable from "no such batch".

**`_BATCH_TASKS` moves to `app.state.batch_jobs`.** Required for the ownership
check to be per-app rather than per-process, and it clears the blocker 2.1 recorded
against batch persistence. Persistence itself is still not added here.

**`verify_jwt` stops returning 422 for a missing header.** `authorization: str =
Header(...)` makes the header *required by FastAPI*, so a request with no
`Authorization` fails validation and returns **422**, not 401. That is wrong on its
own terms, and it would make 2.4's "unauthenticated requests are rejected" test
assert the wrong status. Changed to an optional header with an explicit 401. This
also fixes `/v1/chat/completions` and `/ingress`, which had the same behaviour.

## Done looks like

- [x] With no `*_CORS_ALLOW_ORIGINS` set, a cross-origin request to either service
      comes back with **no** `access-control-allow-origin` header. Two tests, one
      per service.
- [x] With `SCHEDULER_CORS_ALLOW_ORIGINS` naming one origin, that origin is
      allowed and a different origin is not — asserted on the actual response
      header, not on the config object. Two tests.
- [x] `access-control-allow-origin` is never the literal `*` and is never a
      reflected arbitrary origin, in any configuration. Covered by a test that
      sends `Origin: https://evil.example` in both the default and configured cases.
- [x] `"*"` in a configured origin list raises at settings construction, with a
      message naming reflected-origin credentials. One test per service.
- [x] `POST /v1/batch` with no `Authorization` header returns **401** (not 422,
      not 202). Covered by a test.
- [x] `POST /v1/batch` with a valid RS256 JWT returns 202. Covered by a test.
- [x] `GET /v1/batch/{id}` returns the batch to the tenant that submitted it, and
      **404** to a different tenant holding an equally valid token. Two tests.
- [x] Batch state lives on `app.state`; two apps built in one process do not see
      each other's batches. Covered by a test.
- [x] A request with no `Authorization` header to `/v1/chat/completions` returns
      401 rather than 422. Covered by a test.
- [x] `./scripts/verify.sh` passes.

## Out of scope

- **Authenticating the other unauthenticated reads.** `GET /nodes`,
  `GET /nodes/{id}`, `GET /v1/models`, `GET /v1/models/{id}` and `GET /status` take
  no auth dependency, so the node registry — hostnames, regions, IP addresses, GPU
  models, model catalogues — is public to anyone who can reach the Scheduler. That
  is a real gap, it is **not** what 2.3 or 2.4 name, and fixing it silently here
  would hide a decision about whether model discovery is meant to be public (it is
  on the real OpenAI API). Recorded as a **new roadmap line** rather than absorbed.
  Closing CORS reduces its blast radius from "any web page" to "anyone who can
  reach the host"; it does not close it.
- **Persisting batch jobs.** The module-global blocker is removed here, so 2.1's
  deferred piece is now unblocked. Doing it is a separate change.
- **Making `/v1/batch` do any real work.** `submit_batch_job` fabricates its result
  strings and dispatches nothing. This change secures a stub; it does not implement
  it, and that is stated so no one reads "authenticated" as "working".
- **Rate limiting the batch endpoints.** `/v1/chat/completions` has a token bucket;
  batch does not. Out of scope, and worth noting because authentication is not the
  same as a quota.
- **The fallback RSA public key** in `ingress.py:16`, which `verify_jwt` uses when
  no key is configured. Pre-existing, listed in `VERIFY.md`, untouched.

## Verification

```
./scripts/verify.sh
.venv/bin/python -m pytest packages/scheduler/tests/test_cors_policy.py -q
.venv/bin/python -m pytest packages/scheduler/tests/test_batch_auth.py -q
.venv/bin/python -m pytest packages/node/tests/test_cors_policy.py -q
grep -rn 'allow_origins' packages/node/src packages/scheduler/src
```

## Notes / open questions

- Duplicate-module check: the CORS block is configured separately in
  `packages/node/src/node/main.py` and `packages/scheduler/src/scheduler/main.py`.
  These are two FastAPI apps with different settings classes, not one of the six
  duplicated module pairs — there is no shared module to change. The two settings
  fields will be near-identical by necessity; each carries a comment saying so.
- Open: whether the Node's control API should allow *any* cross-origin access. The
  dashboard reaches it through the website's server-side proxy today, so empty is
  right now. If a host ever opens a browser UI served from a different origin on
  their own machine, they configure it — which is the point of making it a setting.
- The measured Starlette behaviour above is version-specific. It is asserted by a
  test against the real middleware rather than trusted from this prose, so a
  Starlette upgrade that changed it would fail the suite rather than quietly
  invalidate the reasoning.
