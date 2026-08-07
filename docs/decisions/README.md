# Decisions

One file per question from **Stage D** of `ROADMAP.md`. Stage D exists because the
code had been assuming answers to questions nobody had written down, and each wrong
assumption was cheap to correct on paper and expensive to correct after another
month of building.

Each record states the decision, the reasoning, **what it costs**, and — the part
that makes these more than prose — **what in the code changes because of it**. A
decision with no consequence in the tree is a decision that was not really made.

| # | Question | Decision | Record |
|---|----------|----------|--------|
| D1 | How does a requester know a node ran the model? | Invite-only trusted hosts, plus sampled canary verification | [D1](D1-execution-integrity.md) |
| D2 | Do the economics close? | **No.** v1 is a donation network with non-redeemable credits | [D2](D2-economics.md) |
| D3 | ToS, acceptable use, operator liability | Written, self-hosted-scoped, **not reviewed by counsel** | [D3](D3-terms-and-liability.md) |
| D4 | Sybil resistance | Invite codes at registration | [D4](D4-sybil-resistance.md) |
| D5 | "Decentralised" versus one instance | Narrow the claim to "community-hosted, single coordinator" | [D5](D5-decentralisation-claim.md) |
| D6 | Is there a network, and who runs it? | **No network.** Ship a self-hosted product; installer defaults to localhost | [D6](D6-is-there-a-network.md) |
| D7 | A second pair of eyes | **Unresolved and unresolvable from inside.** Substitute recorded | [D7](D7-second-pair-of-eyes.md) |
| D8 | The wedge | Self-hosted OpenAI-compatible control plane for hardware you already own | [D8](D8-the-wedge.md) |

## How to read these

They are dated and they are revisable. A decision record is not a promise that the
answer is right; it is a record that the question was asked, answered deliberately,
and that the answer is now load-bearing somewhere. When one turns out to be wrong,
edit it in place with a `## Revised` section rather than quietly deleting it — the
wrong answer is the useful part of the history.

D7 is the one that stays open. It is the only question here that cannot be answered
by the party asking it.
