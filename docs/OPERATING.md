# Operating a node or a coordinator

What you take on by running this. Read it before running this for anyone but
yourself.

**This is not legal advice.** See [D3](decisions/D3-terms-and-liability.md) — the
legal half of that question has not been reviewed by counsel, and the engineering
response was to narrow the product until the exposure is small and clearly assigned.
The narrowing does not eliminate the risks below; it makes them yours to accept
knowingly.

## If you run a **host node**

Your machine executes prompts and returns generated text.

**You are the egress point.** Whatever your node generates leaves your network from
your IP address. The system does no content filtering anywhere — not on input, not on
output, not at the coordinator. If a requester prompts your node into producing
something illegal where you live, your machine produced it and your connection carried
it.

**Residential ISP terms commonly prohibit commercial serving.** Most consumer
broadband contracts forbid running servers or reselling capacity. Under
[D2](decisions/D2-economics.md) there is no payout, which helps, but "not a commercial
service" is a judgement your ISP makes, not you.

**Your node dials out; nothing dials in.** Inference arrives over the Zenoh session
your node opened (ROADMAP 1.1), so no port forwarding is required and no inbound
firewall hole is opened. This is a real safety property and it is why the design is
shaped this way.

**Your node's control API fails closed.** `NODE_NETWORK_AUTH_TOKEN` is generated per
install and required by `/infer`. A node without it serves nothing rather than serving
everyone. Do not blank it to "make it work".

**Anything you can see, you can see.** Prompts routed to your node are readable by you
in full. That is inherent to running inference, and it is why the coordinator sends
you nothing it does not have to.

**Your node writes generated completions to disk.** `node/storage/local.py` saves each
task's output under your temp directory, with **no retention policy and no
configuration to turn it off**. That is a known gap, not a feature — if you serve
other people's prompts, their outputs accumulate on your machine until you delete
them.

## If you run the **coordinator** (Scheduler)

**You are a trusted party, and a single point of failure.** All matchmaking, the
registry, the ledger and every credential live in one process (see
[D5](decisions/D5-decentralisation-claim.md)). If it is down, nothing dispatches. If it
is compromised, every node credential in it is compromised.

**Prompts pass through you.** The Scheduler proxies request bodies to nodes. It does
**not** store them: metering records token counts, model, tenant and serving node, and
`UsageRecord` has no field that can hold prompt or completion text — enforced by
`tests/test_metering_privacy.py`, not by intention. That is the single design decision
keeping your data-protection exposure small. **If you add logging that captures request
bodies, you have undone it.**

**You decide who joins.** Registration requires `SCHEDULER_NETWORK_AUTH_TOKEN` *and*,
once you have issued any, an invite code ([D4](decisions/D4-sybil-resistance.md)):

```bash
scripts/mint_invite.py --issue --label "alice's workstation"
scripts/mint_invite.py --list
scripts/mint_invite.py --revoke <code>
```

The code is shown once; only its SHA-256 is stored. Codes are single-use unless you
pass `--max-uses`, and **revoking one does not evict nodes already admitted under it**
— that is `DELETE /nodes/{id}`, deliberately kept separate so revocation is safe
enough to actually reach for.

**Until you issue your first code, registration is open to anyone holding the fleet
token**, and the Scheduler logs `invite_admission_disabled` at startup saying so. That
fallback exists so upgrading does not lock you out of your own fleet. Once you issue
one, you are in invite mode permanently — including after every code is spent, which
is deliberate: an admission check that switched itself off once its last code was used
would be worse than none.

**You decide who calls.** The gateway requires an RS256 JWT, and with no
`SCHEDULER_JWT_PUBLIC_KEY` configured it refuses **everyone** rather than falling back
to a default — deliberately (ROADMAP C4). `POST /v1/credentials` issues requester
tokens and is guarded by the fleet token, so only you can mint them.

**There is no revocation.** JWTs are stateless: the gateway checks a signature and asks
nothing else, so an issued token is valid until it expires. Issue short ones —
`SCHEDULER_CREDENTIAL_MAX_TTL_HOURS` caps this server-side, default 30 days — and
rotate the signing key if you need to invalidate everything at once. Rotation is a
sequence, not an outage: set the old key as `SCHEDULER_JWT_PUBLIC_KEY_SECONDARY`, sign
new tokens with the new one, and drop the secondary once the last old token has
expired.

## Things that are true about the network path

**Zenoh links are plaintext by default.** Messages that change registry state —
telemetry, heartbeats — are AES-256-GCM enveloped under each node's own token (ROADMAP
2.7). Mesh *inference* is authenticated by HMAC proof-of-possession, which proves who
sent it and that it was not tampered with. **It does not make the prompt confidential
in transit.** If your nodes are not on a network you trust, terminate Zenoh over TLS or
tunnel it. This is not a default and you have to do it.

**`region` is self-asserted.** A node reports its own region and the Scheduler believes
it. It is a matchmaking hint. **It is not a data-residency control**, and must not be
presented to anyone as one.

**CORS is off unless you turn it on.** With no origins configured the middleware is not
installed (ROADMAP 2.3). Adding `*` to the allowlist is a startup error on purpose:
with credentials enabled, Starlette reflects the caller's own origin rather than
sending a wildcard, so `*` is not "permissive", it is "every origin, with credentials".

## What this software does not have

Stated so you do not discover it by needing it:

- **No content filtering, moderation, or abuse pipeline.** None. Anywhere.
- **No rate limiting worth the name.** In-memory, per-instance, resets on restart
  (ROADMAP C5). It absorbs an accident; it does not stop an attacker.
- **No audit log of who read what.**
- **No backups.** Persistence is SQLite at `SCHEDULER_DATABASE_PATH` (default
  `scheduler-state.db`, on by default since ROADMAP C3). On an ephemeral filesystem it
  survives a process restart and is wiped by every redeploy — durability that looks
  like it works. Put it on real disk and back it up yourself.
- **No high availability.** One process.
- **No verification that a node ran the model it claims.** [D1](decisions/D1-execution-integrity.md)
  chose admission control over detection for v1, and the canary mechanism it describes
  is **not implemented**. A trusted host that starts returning garbage will not be
  caught by anything here.
- **No support.** See [`../SECURITY.md`](../SECURITY.md) for the one channel that
  exists, and its honest response times.

## An acceptable-use policy, if you need one

[`ACCEPTABLE_USE.md`](ACCEPTABLE_USE.md) is a template you can adopt. **The software
enforces none of it.** A policy the code does not implement is a document, not a
control.
