# Desk review of the premises — 2026-08-14

Executed per `specs/desk-review-of-the-premises.md`. Web research against the market-
facing premises in `docs/PREMISES.md`, attacking each premise's own falsifier.

## D7 is still open

This is a desk review run by the same party that built the product. It is not the
independent judgement [D7](../decisions/D7-second-pair-of-eyes.md) requires, and it
does not close D7. What it changes: the market premises go from *"asserted by the
author, never checked against anything external"* to *"checked against what strangers
have published, here is what was found."* A human still has to weigh it — that is the
job the operator kept for themselves, and it is the right one to keep.

## Read this caveat before the findings

**The network egress proxy blocked most primary user-voice sources.** Reddit,
Hugging Face forums, personal blogs, and the one direct competitor-comparison page
(`sharedllm.org`) were all refused. What got through: GitHub, company documentation,
and the search engine's own **summaries** of pages I could not then open.

The consequence, stated plainly: the strongest evidence below is from **primary
GitHub/company sources** (Kalavai's own docs, Petals' repo). The user-sentiment
evidence is **search-engine paraphrase I could not verify verbatim** — it is
directionally consistent and it is weaker than a quote, and it is labelled as such
every time. R3 ("the users' own words") is the pass that suffered most; treat its
findings as leads, not proof. A second run from an unrestricted network would
strengthen or overturn the sentiment findings, not the primary-source ones.

Evidence tags used below: **[primary]** = I opened the source. **[summary]** =
search-engine paraphrase, unverified verbatim. **[discarded]** = SEO/affiliate
content farm, no evidentiary weight.

---

## P2 — "NAT traversal for GPU hosts is the differentiator" → **FALSIFIED** (as stated)

The falsifier written in `PREMISES.md`: *"the target user already runs Tailscale, in
which case this is re-solving a solved problem."*

Every angle I searched returned the falsifier as true. Reaching your own GPU box from
outside your network is a **solved, well-trodden, "just works" problem**, and Tailscale
is the near-universal answer:

- Tailscale's own guidance positions self-hosted-AI-from-anywhere as a first-class,
  zero-config use case; free tier is 6 users / unlimited devices. [summary,
  `tailscale.com/blog/self-host-a-local-ai-stack`]
- A dense field of independent 2026-dated how-to guides exists specifically for
  "access Ollama remotely with Tailscale" — the volume itself signals a solved,
  SEO-saturated problem, not an open one. [summary, multiple: `logarithmicspirals.com`,
  `kdnuggets.com`, `glukhov.org`, `runaihome.com`]
- An HN commenter, on setting up Tailscale for their local LLM: *"there's no going
  back."* [summary, via HN threads — could not open the thread to verify verbatim]

**The precise verdict, because the wording matters.** P2 as written describes
single-user remote access — "reach *my* box." That framing is falsified: Tailscale
solves it for the target user, for free, today. What is **not** falsified is a
different claim P2 does not actually make: *multi-party* NAT traversal, where many
strangers' nodes join one pool and a coordinator must reach all of them. Tailscale is
single-tenant-shaped and does not cleanly do that. So the differentiator, if one
survives, is **pooling across parties**, not **NAT traversal** — and that relocates
the load-bearing claim onto P1, which is weaker.

Confidence in verdict: **high** for the single-user framing as written.

## P1 — "Someone wants to serve inference from hardware they own" → **MIXED**

Two claims are bundled here and the evidence splits them cleanly.

- *Local single-machine inference demand* — **strongly true**. Ollama and LM Studio
  have large user bases; this was never in doubt.
- *Federation across several people's machines* (the part D8 rests on) — **no demand
  evidence found, and the market signal leans negative.** Every distributed-consumer-
  GPU project I found is either research/hobby or has moved away from the crowd model
  (see the landscape table). I found no primary evidence of consumers wanting to pool
  GPUs across people for inference *as a product*. The base-rate observation that
  consumer cards can't hold big models [summary] is a reason the capability *could*
  matter — it is not evidence anyone wants it enough to adopt one.

Confidence: the split itself is high-confidence; the federation half is "no evidence
found", which is a finding, not a neutral.

## P3 — "The economics do not close for a marketplace" → **SUPPORTED** (weakly, indirectly)

I could not get primary host-earnings numbers (the sources were SEO farms
[discarded], e.g. `earnifyhub.com`). But the **market's own structure** is consistent
with P3's conclusion and is primary-sourced:

- The best-funded decentralised-compute company, Prime Intellect ($15M+, Founders
  Fund; Karpathy among angels), makes its money aggregating **datacenter/cloud** GPUs
  (Akash, io.net, Vast.ai, Lambda) and on **distributed training** (INTELLECT-2/3) —
  not on pooling consumer home GPUs for inference. [summary, `sacra.com`,
  `primeintellect.ai/blog/compute`]
- Kalavai — the project closest to this product's original vision — **pivoted off the
  crowd model entirely** (next section).

Both serious commercial actors concluded the value is in datacenter aggregation and
training, not the consumer inference crowd. That is what P3 predicts. Confidence:
medium; this is the market voting with its feet, not a metered node.

## P7 — "Ollama is a sufficient inference backend" → **MIXED / partially falsified for serving**

Ollama is sufficient for a node's *local, single-user* use. But this product is a
multi-user *serving* network, and for serving, the community standard is vLLM:

- 2026 benchmarks put vLLM at ~16× Ollama's throughput under concurrency; the
  repeated framing is "Ollama for local iteration, vLLM in production" and *"shipping
  Ollama to production and watching it fall over at 10 concurrent users."* [summary,
  `sitepoint.com`, `spheron.network`, multiple]

A serving network built on the prototyping backend is a real tension. P7's own
falsifier ("the target user runs vLLM or llama.cpp and will not add Ollama") is
partially borne out for exactly the multi-user case the product is for.

## P4, P5, P6, P8, P9 — **NO EVIDENCE FOUND (out of web scope)**

These are premises about execution integrity, coordination, data handling, and this
repo's own process. Web research says nothing about them; they were never expected to
be reachable this way. Not assessed rather than assessed-and-cleared.

---

## R2 — The competitive landscape and the graveyard

Nobody has died, but the pattern in who-moved-where is the finding.

| Project | Status | Shape | Signal |
|---|---|---|---|
| **Petals** (BigScience) | **Alive.** 10.5k stars, public swarm live (`health.petals.dev`, `chat.petals.dev`), no maintenance warning. [primary, GitHub] | BitTorrent-style consumer-GPU inference | Proves the *capability* is real and sustainable as **research/community infra**. Not a commercial product. |
| **Kalavai** | **Pivoted.** Now "a managed computing platform… on-demand distributed compute" leveraging "spare **data center** capacity" for "developers and research teams." [primary, their GitHub docs] | Was crowd-GPU; now enterprise/datacenter | The closest thing to *this product's original vision* **left that vision.** The single most on-point finding here. |
| **Prime Intellect** | **Thriving**, $15M+ funded | Decentralised **training** + aggregating **datacenter/cloud** GPUs | The serious money went to training + datacenter, **not** consumer inference federation. [summary] |
| **Exo** | Alive; viral demos | Apple-Silicon LAN clustering | *"demos are not infrastructure… the gap between 'this worked on a LAN with three Macs' and 'this is a network you can rely on' is enormous."* [summary, via `sharedllm.org` — a competitor, so discount] |
| **Tailscale** | Dominant | Single-user secure remote access | Owns the P2 problem for the individual. |
| LocalAI, Distributed Llama, NeuroMesh, SharedLLM, Parallax | Various | Assorted distributed-LLM tech | The space is **crowded with capability**. Capability is not the scarce thing. |

The consistent shape: **technical capability for distributed consumer-GPU inference is
abundant and not scarce. Commercial gravity is in enterprise/datacenter aggregation
and distributed training. The consumer-home-GPU-inference-federation niche is where
projects start and the place at least one of them deliberately left.**

## R4 — Prosecution and defence, on the evidence gathered

**Prosecution (this should not be built as pitched).** The remote-access problem P2
leans hardest on is solved for the individual by Tailscale, for free, today. The
multi-party federation the product actually does is a crowded research/hobby space
whose closest commercial competitor (Kalavai) explicitly pivoted to enterprise, and
whose best-funded neighbour (Prime Intellect) aggregates datacenter GPUs for training.
The serving backend (Ollama) is the wrong one for the multi-user serving this is for.
No primary evidence of unmet consumer demand for cross-party GPU pooling was found.
The product risks being a well-engineered answer to a question the market has already
answered a different way.

**Defence (there is still a real gap here).** Local-inference demand is large and real.
Petals proves the capability is technically sound and can sustain a live swarm. The
privacy / data-residency / own-hardware / no-prompt-persistence angle (P6) is a genuine
differentiator that Tailscale-plus-cloud does not address. Multi-party NAT traversal is
genuinely awkward and *not* cleanly solved by Tailscale. And competitors pivoting to
enterprise could mean the consumer niche is **underserved**, not **nonexistent**.

**The asymmetry, stated as the spec requires.** The prosecution rests on concrete,
mostly-primary artifacts: Kalavai's own pivot language, Prime Intellect's funding and
focus, vLLM benchmarks, Tailscale's ubiquity. The defence rests mostly on *reasoning*
— the privacy angle, "underserved not nonexistent" — plus one concrete point (Petals
is alive, and it is not a commercial product). On the evidence actually gathered, the
prosecution is the better-supported side. That is not a verdict on the product; it is
a statement about which case the evidence currently backs, and it is the honest read.

## What a human reviewer should weigh

1. Is the differentiator **NAT traversal** (falsified for the single user) or
   **cross-party pooling** (unevidenced demand)? P2 as written points at the first;
   the product's value, if any, lives in the second. That relocation is the crux.
2. Kalavai walked the exact path this project is on and turned toward enterprise. Was
   that a market lesson, or a fundable-business lesson that a non-commercial /
   privacy-first project does not have to obey?
3. If the serving backend should be vLLM, not Ollama, how much of the current node
   design survives?

None of these is answerable from a desk. They are the questions to put to the second
pair of eyes D7 asks for.

---

## Addendum — independent second run (Gemini Deep Research, 2026-08-14)

The operator re-ran the market questions through a **different model** (Gemini Deep
Research), on infrastructure **not behind this environment's egress proxy**, and —
the part that matters — **without being shown any verdict above.** It reached the same
four verdicts independently and opened the primary reddit/HN sources this review could
not. That independent convergence is the strongest single result of the whole
exercise. Three caveats keep it honest.

**1. It is not a human, and it had this project's framing.** The concept description
it was given originated here. A second model agreeing is corroboration; it is not the
external human judgement D7 requires. It also writes with a confident, overheated
register ("mathematically undeniable", "killing blow", "physics prohibits") — exactly
the fluent-certainty an AND-review must discount rather than be moved by.

**2. Its single most dramatic argument misfires against *this* product.** Gemini's
latency/"physics" killing blow assumes **tensor-parallel sharding of one model across
WAN nodes** (architecture A). This product's v1 does **not** do that — split inference
is cut, and `CLAUDE.md` states the working path routes a whole request to **one node
holding the whole model** (architecture B). WAN then carries only a prompt and a
reply, for which residential latency is fine. So the most forceful argument in the
Gemini report is aimed at a design v1 does not ship. This is the clean example of why
a confident second opinion still gets checked: **it was right about the direction and
wrong about the mechanism, and only reading this specific codebase catches that.**

**3. The correction rescues the *physics*, not the *demand*.** Once B is understood,
the product is "a router / OpenAI gateway across several people's single-node Ollama
boxes, with NAT traversal." The technical-impossibility case dissolves — but every
**demand** finding above survives it untouched: Tailscale still solves reaching a node
(P2), there is still no evidence anyone wants to pool across people (P1), and the
privacy paradox still applies because a prompt still leaves for someone else's machine.
The market case against is intact; the engineering case against was overstated.

New evidence it surfaced that this review lacked. **The verbatim quotes are unverified
from here** — Deep Research can synthesise a plausible quote at a plausible URL, the
exact silent failure `specs/desk-review-of-the-premises.md` names — so treat these as
leads to confirm, not settled facts:

- **P2, the quote the proxy denied me:** *"I use tailscale, its like 1 command… works
  super well and its free for personal."* Direct confirmation of the P2 verdict.
- **P1, sharpened:** the demand that exists is for client-server access to **one**
  strong node — *"Bought a 5090… now I'm just lending the extra compute to my
  friends"* — which people already meet by sharing an Ollama endpoint over Tailscale,
  needing no product. Demand for genuine cross-machine pooling: still none found.
- **A grave I missed:** AI Horde, a voluntary-compute pool, cited as foundering on the
  incentive-plus-latency problem — a direct precedent for the no-payment model here.
- **Exo:** reported as having retreated to Thunderbolt-5 **LAN**, off the internet
  entirely — consistent with, and stronger than, the "demos are not infrastructure"
  line in the table above.

**Net after reconciliation.** Two independent reviews, different models, different
networks, no shared verdicts, converged: the differentiator P2 names is solved
(Tailscale), the demand P1 needs is absent, the competitors pivoted to enterprise, and
Ollama is the wrong serving backend. The privacy paradox — a prompt routed to a peer's
box breaks the privacy that motivates local AI — is the sharpest surviving argument and
belongs in `PREMISES.md` as its own premise if the product continues. The one thing the
second run got wrong is instructive: it declared the architecture physically impossible
by attacking a design v1 doesn't ship, and only the codebase refutes it. **D7 is still
open** — two models are still not a person — but the market premises are now the most
externally-tested claims in this repository.
