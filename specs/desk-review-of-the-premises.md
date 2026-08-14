# Spec: Desk review of the premises

## What this does

Attacks the nine premises in `docs/PREMISES.md` using web research, and records what
was found — including, especially, where nothing was found.

**This does not close [D7](../docs/decisions/D7-second-pair-of-eyes.md), and any
output claiming it does is wrong.** D7 asks for a judgement made by someone who is
not the party building this. A model I run is the same party. What this changes is
narrower and still worth having: D7 goes from *"nobody has looked"* to *"desk
research was done, here is what real people said, human judgement still missing."*

## The distinction the whole thing rests on

There are two things an AI could do here, and only one of them is worth anything.

**Worthless: asking a model whether the premises are right.** It will produce fluent,
confident prose in either direction. It has no privileged access to whether people
want this. That is the same-party failure D7 names, wearing a new hat.

**Valuable: using a model to find what real people already wrote.** Forum posts,
GitHub issues, abandoned projects, competitor documentation. That evidence is
*external* — written by humans who have never heard of this project and have no stake
in it. The model is a search-and-retrieval instrument, not a judge.

**So the governing rule: a finding is a dated quote from an identifiable human at a
URL. Nothing else counts as evidence — including the model's own reasoning, however
persuasive.** A pass that produces good arguments and no quotes has produced nothing.

## The four passes

### R1 — Falsification hunt

Every premise in `docs/PREMISES.md` already carries a written falsifier. That is the
brief: **go and find evidence that the falsifier is TRUE.**

Not balance. Not "explore both sides." Confirmation is the default failure mode of
any search — you find what you look for — so the instruction is to look for the
disproof. If a premise survives a genuine attempt to kill it, that means something.
If it survives a search that was trying to be fair, that means nothing.

Priority order, by stated confidence: **P2 first** (medium-low, "the premise most
likely to be wrong", and the one the whole pitch rests on), then P1, P7, P3.

### R2 — Prior art and the graveyard

Has this been built? Petals, Exo, Kalavai, Prime Intellect, vast.ai, Salad, Together,
Hivemind, and anything else the search surfaces.

For each: is it alive, and if it died, **why**? A dead project with a public
post-mortem is the most valuable artifact available without talking to users —
someone already ran the experiment and wrote down the result.

Specifically for P2: does anything already do NAT traversal for self-hosted
inference, and do its users treat that as the valuable part?

### R3 — The users' own words

Where these people actually talk: r/LocalLLaMA, Hacker News, GitHub issues on
`ollama`, `exo`, `tailscale`, `open-webui`, and equivalent.

Find people describing this problem **unprompted, in their own words**. Not "would
you want X" — nobody was asked. What did they complain about on their own?

Two specific questions:
- Do people describe wanting to reach their own GPU box remotely, and what do they
  use today?
- When they mention Tailscale/ngrok/a VPN for this, do they describe it as *solved*
  or as *annoying*?

**If nobody complains about the problem this product solves, that is the single most
important finding available, and it must be reported as a finding rather than as an
empty section.**

### R4 — Adversarial pass

One agent, one brief: **argue this product should not be built.** It may use only
evidence gathered in R1–R3 — no new speculation. Its output is the case for the
prosecution, as strong as the evidence allows.

Then, separately, the case for the defence on the same evidence. Where the two are
asymmetric — one side has quotes and the other has only reasoning — say so plainly.

## Done looks like

- [ ] `docs/review/desk-review-<date>.md` exists, with one section per premise P1–P9.
- [ ] Each premise ends with exactly one verdict: **falsified** / **supported** /
      **no evidence found** / **mixed**. No fifth option, no hedging into prose.
- [ ] Every "supported" or "falsified" verdict cites **at least two independent
      sources**, each with a URL, a direct quote, and a date.
- [ ] Every source is date-checked, and any older than ~18 months is flagged — a 2023
      complaint about remote GPU access may have been solved by 2026, and treating a
      stale complaint as current evidence is the easiest way to get this wrong.
- [ ] "No evidence found" appears wherever true, is never smoothed into a paragraph
      of plausible reasoning, and is stated as an interesting result rather than an
      apology.
- [ ] R2 lists every comparable project found, alive or dead, with a one-line status
      and a link — including any that make this project redundant.
- [ ] The prosecution and defence cases from R4 are both recorded verbatim.
- [ ] `docs/PREMISES.md` is updated: any premise whose confidence the evidence moves
      gets its confidence line changed, **with the source cited inline**.
- [ ] The report's own first section states that D7 remains open.

## Out of scope

- **Closing D7.** Stated twice on purpose. A desk review is not a reviewer.
- **Changing the product based on the findings.** This gathers evidence. What to
  build in response is a decision for a human, recorded as a decision record if it
  happens.
- **Surveying people directly.** Posting a question to a forum is a different
  activity with different ethics and a different failure mode, and it is not this.
- **Upgrading any confidence in `PREMISES.md` on the model's own judgement.** Only
  cited external evidence may move a confidence line, in either direction.

## Verification

There is no gate for this — it produces prose, not code. What is checkable:

```
# every cited URL resolves and the quote appears at it
# no verdict of "supported"/"falsified" has fewer than two sources
```

Both are worth checking by hand on a sample, because a fabricated quote with a
plausible URL is the specific way this pass fails, and it fails silently.

## Notes / open questions

- **The most likely disappointing outcome is that the searches return very little**,
  because the niche is small and self-hosted-inference users are not loud in indexed
  places. That is a real result about the size of the market and must be reported as
  one, not padded.
- **The second most likely failure is fabricated evidence** — a confident quote that
  does not exist at the URL given. This is why two independent sources and verbatim
  quotes are required, and why spot-checking is in the verification section.
- P8 and P9 are premises about *this repository's own process*, not about the market.
  Web research says little about them; they are included for completeness and are
  expected to come back "no evidence found", which is fine.
