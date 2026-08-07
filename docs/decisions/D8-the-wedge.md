# D8 — The wedge

**Date:** 2026-08-07
**Status:** Decided

## The question, restated

Petals, Together, Akash, io.net, Prime Intellect, Hyperbolic, Bittensor. Write the
one paragraph explaining why someone picks this instead. If it is hard to write, that
is the finding.

## It was hard to write, and that is the finding

The first three attempts all described a compute marketplace, and every one of them
lost on every axis to an incumbent: cheaper per token, more models, real SLAs, actual
supply. [D2](D2-economics.md) then established that the marketplace framing is not
merely crowded but arithmetically unavailable — a residential host loses money at
current prices. There is no wedge for the product as it was being described.

There is one for a different, smaller product, which is most of what the code already
is.

## The paragraph

> **Public Intelligence is an OpenAI-compatible control plane for hardware you
> already own.** You point it at machines you or people you trust control — a
> workstation with a GPU, a lab's spare box, three laptops in a research group — and
> it gives you one authenticated `/v1/chat/completions` endpoint that routes across
> all of them, including the ones behind NAT, with no port forwarding and no VPN.
> You pick it over Together or Hyperbolic because your data never leaves machines you
> control. You pick it over running Ollama directly because Ollama is one machine
> with no auth, no routing, no fleet view, and no story for the laptop on someone
> else's network. You pick it over Akash or io.net because you are not renting
> capacity, you are federating capacity you already have, so there is no token, no
> marketplace, and nothing to price. And you pick it over Petals because you want a
> whole model on one machine served fast, not one model split across strangers.

## Why this is defensible where the marketplace framing was not

- **It does not compete on price**, so [D2](D2-economics.md)'s conclusion stops being
  fatal and starts being irrelevant: nobody is trying to profit per token.
- **It does not need a network to exist**, which is exactly what
  [D6](D6-is-there-a-network.md) decided not to build.
- **It makes [D1](D1-execution-integrity.md) small**, because the host and the
  requester are usually the same organisation. Execution integrity across mutually
  suspicious strangers is the hardest problem in this space; this framing sidesteps it
  rather than pretending to solve it.
- **The NAT traversal is the actual differentiator.** Reaching a GPU on a home or
  campus network, from outside, without port forwarding, is genuinely annoying to
  build. ROADMAP 1.1 built it over Zenoh. It is the one piece of this system that
  someone would rather adopt than write.

## What this costs, stated plainly

- **The market is much smaller.** "Teams with idle GPUs and a compliance reason to
  keep data in-house" is a real segment and a narrow one. The previous framing
  addressed a large market it could not actually serve, which is worth less.
- **"Community-owned decentralised infrastructure" is gone**, along with everything
  built on it. See [D5](D5-decentralisation-claim.md).
- **The NAT-traversal claim is not yet substantiated across two machines** (ROADMAP
  1.5 is partial: one process, TCP loopback, a real router). The wedge rests on the
  one thing that has not been demonstrated on real hardware. That is the top
  engineering priority this decision creates, and it is why 1.5 stops being optional.

## What changes in the code

- README, website copy and `PROJECT.md` lead with the self-hosted framing.
- ROADMAP 1.5 is promoted: cross-machine inference is now the load-bearing claim.
- Stage 3's payout machinery is cut to accounting only (see D2). Credential issuance
  (3.1) stays, because a team still needs to hand its developers a token.
