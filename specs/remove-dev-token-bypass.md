# Spec: Remove the `dev_*` bearer token auth bypass

## What this does

Removes the hardcoded development backdoor in the Scheduler's JWT verifier that
authenticated any bearer token starting with `dev_` (plus the literals `dev`,
`local`, `test`) as the `tenant-dev` principal, and removes the website proxy's
default of sending `Bearer dev_token` when a request arrives with no auth header.
After this change, RS256 signature verification is the only way to authenticate,
and an unauthenticated request fails instead of silently succeeding.

## Done looks like

- [ ] `Scheduler/src/scheduler/api/ingress.py` contains no branch returning claims
      without verifying a signature — `grep -n "dev_token" Scheduler/src` is empty
- [ ] `website/src/app/api/chat/completions/route.ts` never synthesises an
      `Authorization` header; a request with none gets a 401 from the proxy
- [ ] `Bearer dev_token`, `Bearer dev_anything`, `Bearer dev`, `Bearer local`,
      and `Bearer test` all return **401** on `/api/v1/tasks/submit` and
      `/v1/chat/completions`
- [ ] A validly signed RS256 token with a `tenant_id` claim still returns non-401
      (positive control — proves the fix rejects bypasses, not everything)
- [ ] Regression test exists in `Scheduler/tests/test_auth_bypass_regression.py`
      and was observed **failing before** the fix and passing after
- [ ] An RS256 keypair is generated and a token-minting script exists, so the
      playground has a working auth path

## Out of scope

- **`TELEMETRY_SECRET_KEY`** hardcoded default in `Node/src/node/core/telemetry.py:175`
  and `Scheduler/src/scheduler/core/zenoh_router.py:255` — explicitly excluded.
- **CORS wildcard** (`allow_origins=["*"]` with `allow_credentials=True`) in both
  `main.py` files — explicitly excluded.
- **`FALLBACK_PUBLIC_KEY`** at `ingress.py:16` stays. It fails closed (nobody holds
  the private half), so it is not a bypass. Removing it is a separate change.
- **`/v1/batch` has no auth dependency at all** — discovered while checking this
  fix. A real hole, but a different one. Not touched.
- Rotating or issuing tenant credentials operationally; this produces one keypair
  and a mint script, not a key-management system.

## Verification

```bash
Scheduler/.venv/bin/python -m pytest Scheduler/tests -q
Node/.venv/bin/python      -m pytest Node/tests      -q
Node/.venv/bin/python      -m pytest tests           -q
grep -rn "dev_token" Scheduler/src website/src        # must be empty
```

Then `VERIFY.md` in full as a separate pass.

## Notes / open questions

- The deployed Render gateway needs `JWT_PUBLIC_KEY` set to the generated public
  key before `/playground` works again. Until then it correctly rejects everything.
- `website/src/app/api/chat/completions/route.ts:17`'s `SCHEDULER_NETWORK_AUTH_TOKEN`
  branch sends that value as a **Bearer JWT**, but Scheduler validates
  `network_auth_token` via the `X-Network-Auth-Token` header (`api/auth.py`) — a
  different mechanism. That branch only works if the value is itself a valid minted
  JWT. Confusing naming, left as-is to keep this change scoped.
