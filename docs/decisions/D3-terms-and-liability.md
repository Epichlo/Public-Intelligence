# D3 — Terms of service, acceptable use, and operator liability

**Date:** 2026-08-07
**Status:** Decided for the self-hosted scope. **Not reviewed by a lawyer.**

## Read this first

**Nothing in this record or in the documents it produces is legal advice, and none
of it has been reviewed by counsel.** The ROADMAP line for D3 says it "needs actual
legal advice, not a guess". That has not happened and cannot happen from inside this
repository. What follows is the *engineering* half of the answer: the scope was
narrowed until the legal exposure is small and clearly assigned, and the residual
risk is written down instead of being carried silently.

**Before this project is operated as a service for other people, D3 must be reopened
with a lawyer.** That is a gate on operating a network, not on shipping the code.

## The question, restated

Hosts run arbitrary prompts from strangers on home machines, egressing from a
residential IP. There is no ToS, no acceptable-use policy, no abuse pipeline, no
content policy. Separately, prompts are personal data routed to unvetted third
parties worldwide, with no data-processing agreement and no real residency control
(`region` is self-asserted by the node and believed).

## Decision

**Collapse the exposure by narrowing the product, then document what is left.**

[D6](D6-is-there-a-network.md) already removed the hardest part: with no operated
network, there is no service being provided to third parties, so there is no
controller/processor relationship to paper and no abuse pipeline to staff. What
remains is a **software licence** question, answered by Apache-2.0 (ROADMAP N3),
plus honest documentation of the risks an *operator* takes on if they run one.

Concretely, three documents ship:

1. **`LICENSE`** — Apache-2.0. Explicit patent grant, explicit "AS IS" disclaimer of
   warranty and limitation of liability. This is the load-bearing legal document for
   a self-hosted product.
2. **`docs/OPERATING.md`** — the risks of running a coordinator or a host node,
   stated in engineering terms: residential ISP terms of service commonly prohibit
   commercial serving; prompts you serve are other people's data and you can read
   all of them; you are the egress point for whatever your node generates; there is
   no content filtering anywhere in this system.
3. **`docs/ACCEPTABLE_USE.md`** — a template AUP an operator can adopt, plus the
   statement that **the software enforces none of it**. A policy the code does not
   implement is a document, not a control, and saying so is the entire point.

## The data-protection position, stated rather than assumed

- **Prompts are not persisted by the Scheduler.** Metering (ROADMAP 3.2) records
  token *counts*, model, tenant and serving node — deliberately **not** prompt or
  completion text. This is the single design decision that keeps the exposure small,
  and it is enforced by a test, not by intention.
- **`region` is self-asserted and is not a residency control.** It is a matchmaking
  hint. Any surface implying otherwise is corrected.
- **Zenoh links are plaintext by default.** Mesh messages that change registry state
  are AES-256-GCM enveloped (ROADMAP 2.7); the inference payload is authenticated by
  HMAC proof-of-possession but is **not confidential in transit** unless the
  operator configures TLS on the router. This is now stated in `docs/OPERATING.md`
  instead of being a property one has to derive from the transport code.

## What this costs, stated plainly

- **It is a narrowing, not a solution.** If the product ever grows back toward
  "strangers serving strangers", every question here returns, larger.
- **An operator who ignores `OPERATING.md` is exposed**, and the licence disclaimer
  is the only thing between them and that. Apache-2.0's disclaimer is standard and
  strong, and it is not a substitute for advice.
- **No abuse reporting path exists**, because there is no operated service to report
  abuse to. `SECURITY.md` covers vulnerabilities in the code, which is a different
  thing and should not be confused for one.

## What changes in the code

- `LICENSE` (Apache-2.0), `SECURITY.md`, `CONTRIBUTING.md` — ROADMAP N3.
- `docs/OPERATING.md`, `docs/ACCEPTABLE_USE.md`.
- Metering records no prompt or completion text, with
  `tests/test_metering_privacy.py` failing if a field that could carry one appears.
- `region` documented as self-asserted everywhere it surfaces.
