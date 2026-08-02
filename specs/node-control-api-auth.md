# Spec: Authenticate the Node's control and inference API

## What this does

Every route on the host Node was unauthenticated while the server bound
`0.0.0.0` by default, so anyone who could reach the port could stop the node,
read its sandbox logs, or spend its GPU. This adds a shared-secret credential
(`X-Network-Auth-Token`, from `Settings.network_auth_token`) to the four control
routes plus `POST /infer` and `GET /models`, generates the secret per install,
and forwards it from the dashboard proxies.

## Done looks like

- [ ] All 4 routes in `node/api/control.py` reject requests without the
      credential (401), enforced at router level so a route added later is
      protected by default
- [ ] `POST /infer` and `GET /models` also reject without the credential
- [ ] `GET /health` and `GET /health/ready` stay open for container healthchecks
      and liveness probes
- [ ] A node with **no** token configured rejects every protected route
      (fail closed) — deliberately unlike `scheduler/api/auth.py`
- [ ] Credential comparison is constant-time (`hmac.compare_digest`)
- [ ] Regression test observed failing before the fix and passing after, covering
      missing / wrong / unconfigured credentials plus a positive control
- [ ] `install.sh` and `install.ps1` generate a 64-hex-char token into
      `Node/.env`, including an upgrade path for existing installs
- [ ] The three dashboard proxies forward the credential and surface an
      actionable message on 401
- [ ] All suites pass; CI green

## Out of scope

- **`TELEMETRY_SECRET_KEY`**, **CORS wildcard**, **`/v1/batch` having no auth** —
  explicitly excluded; separate issues.
- **Per-tenant identity on the Node.** This API has one principal (the machine's
  owner). No `tenant_id`, no rate limiting, no attribution.
- **Rotating the credential** — the installer generates one; rotation is manual
  (edit `Node/.env`, restart).
- **Pre-existing test pollution.** Other Node test modules leave `AsyncMock`s on
  `app.state` and never clean up; `test_control_api_auth.py` works around it with
  `raise_server_exceptions=False` rather than fixing the leak.
- **The `/health` routes' own exposure** — they disclose Ollama reachability and
  node readiness without a credential. Accepted so probes keep working.

## Verification

```bash
Node/.venv/bin/python -m pytest Node/tests/test_control_api_auth.py -q
Node/.venv/bin/python -m pytest Node/tests -q
bash -n install.sh && ./install.sh --dry-run
(cd website && npx tsc --noEmit)
```

## Notes / open questions

- **Why a shared secret rather than the Scheduler's RS256 JWT:** the JWT exists
  to attribute requests to mutually-untrusting tenants for rate limiting. The
  Node has one principal and consumes no claims, so RS256 would mean distributing
  an issuer key to every residential node and minting per-node tokens — key
  management for a single-user control plane. The chosen header is already used
  by `node/clients/scheduler.py` outbound and validated by `scheduler/api/auth.py`
  inbound, so both services now share one scheme.
- **Fail-closed is a deliberate divergence.** `scheduler/api/auth.py` returns
  successfully when no token is configured. On a `0.0.0.0`-bound control API that
  behaviour *is* the vulnerability, so this rejects instead.
- **Upgrade impact:** existing installs have no token and will reject all control
  requests until `NODE_NETWORK_AUTH_TOKEN` is set. Re-running the installer adds
  one without overwriting other settings. The dashboard needs `NODE_AUTH_TOKEN`
  set to the same value.
- `install.ps1` syntax could not be validated locally (no `pwsh`); CI's Windows
  leg executes it for real.
