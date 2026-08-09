# Acceptable Use Policy (template)

**Status: a template, not a control.** This project ships no content filtering, no
moderation, and no abuse pipeline. Adopting this document does not cause the software
to enforce any of it. It exists so an operator who needs a policy has one to start
from, and so nobody mistakes the absence of a policy for the absence of a problem.

**Not legal advice.** See [D3](decisions/D3-terms-and-liability.md). If you are
operating this for people other than yourself, have a lawyer read whatever you adopt.

---

## Scope

This policy governs use of a Public Intelligence deployment — the coordinator
(Scheduler) and every host node registered with it. "Operator" means whoever runs the
coordinator. "Requester" means anyone holding a credential that can call the gateway.
"Host" means anyone running a node.

## Prohibited use

Requesters must not use the deployment to:

1. Generate, solicit, or distribute content that is illegal where the operator, the
   requester, or **any host that may serve the request** is located. Hosts are
   volunteers on residential connections; a request routed to one makes their machine
   and their IP the origin of whatever comes back.
2. Generate sexual content involving minors, or content that sexualises a real person
   without consent.
3. Generate content intended to harass, defame, impersonate, or threaten a specific
   person.
4. Produce material to deceive at scale — spam, astroturfing, synthetic reviews,
   fabricated news, or impersonation of a real organisation.
5. Develop malware, exploits, or intrusion tooling against systems the requester is not
   authorised to test.
6. Attempt to extract another tenant's data, another node's credentials, or the
   coordinator's signing keys.
7. Circumvent rate limits, quotas, or authentication, including by registering nodes to
   obtain dispatch the operator did not grant.
8. Submit personal data of third parties that the requester is not permitted to
   disclose. **Prompts are visible in full to whichever host serves them, and that
   host's machine writes the generated output to its own disk.**

## Obligations that fall on the operator, not the requester

- **Tell requesters that hosts can read their prompts.** This is inherent to the
  architecture and is not something the software hides or could hide.
- **Tell hosts what they are agreeing to serve.** A host with no idea what runs on
  their machine cannot consent to it.
- Do not represent `region` as a data-residency guarantee. It is self-asserted by the
  node and believed.

## Enforcement

Enforcement is manual and is the operator's job. The software provides two levers, and
both are blunter than they should be:

- **Evict a node** (`DELETE /nodes/{id}`) — the removal is logged and reports whether
  the node is actually gone (ROADMAP 2.5). This is the precise one.
- **Rotate the fleet token** (`SCHEDULER_NETWORK_AUTH_TOKEN`) — stops new
  registrations, and requires re-configuring every legitimate node at the same time.
  Per-node invite codes ([D4](decisions/D4-sybil-resistance.md)) would make this
  targeted; they are **decided and not implemented**.

There is **no mechanism to revoke an issued requester credential** before it expires,
other than rotating the signing key — which invalidates every token at once. This is
inherent to stateless JWTs, not an oversight: the gateway verifies a signature and
never consults a revocation list, and adding one would mean a lookup on every request.
Issue short-lived tokens (`POST /v1/credentials` caps at
`SCHEDULER_CREDENTIAL_MAX_TTL_HOURS`, default 30 days) rather than relying on
revocation that does not exist.

There is also **no way to detect a host returning garbage.** [D1](decisions/D1-execution-integrity.md)
chose admission control over detection for v1, and its canary mechanism is not built.
Enforcement against a misbehaving *host* is therefore reactive and depends on someone
noticing.

## Reporting

Abuse of a specific deployment goes to that deployment's operator. This project does
not operate one ([D6](decisions/D6-is-there-a-network.md)) and therefore has no abuse
inbox. Security vulnerabilities *in the software* are a different thing and go to
[`../SECURITY.md`](../SECURITY.md).

## Changes

An operator adopting this should date it, put it somewhere requesters can read it
before they get a credential, and treat changes as changes to an agreement rather than
edits to a file.
