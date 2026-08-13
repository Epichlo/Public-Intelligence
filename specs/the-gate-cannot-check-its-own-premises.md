# Spec: The gate cannot check its own premises

## What this does

Every defect that has escaped this repository escaped the same way, and the pattern
is now well enough evidenced to design against. This spec does not fix a bug. It asks
two agents, deliberately given **different information**, to decide what mechanism —
if any — would have caught the escapes, and to record that as decision D10.

The problem, stated so it can be attacked: **`./scripts/verify.sh` measures whether
the code does what someone said it should do. Nothing measures whether that claim was
ever true of anything outside this process.** A test asks "does it still do what I
said". A ratchet asks "did this get worse". Neither can ask "should it do this at
all", or the sharper question, "has any of this ever touched reality".

## The evidence this is real, not a worry

Six escapes, all from this repository, none caught by 850+ passing tests and a green
gate. They are listed because a design that does not explain all six is not the fix.

| # | Escape | Found by | What the tests were doing |
|---|--------|----------|---------------------------|
| E1 | `bootstrap.public-intelligence.net` was written into every generated `.env`. It is NXDOMAIN and never resolved once. | A person reading it | Passing. Nothing ever resolved the name. |
| E2 | Six defects blocked a node from running on a second physical machine — four of them Windows-only, because `install.ps1` had never been executed by anything, ever. | A human running it | Green. `verify.sh` is bash; the Windows CI legs also run the bash gate. |
| E3 | Every node either installer produced was named `node-local`. `env_prefix="NODE_"` resolves `node_id` to `NODE_NODE_ID`; both installers wrote `NODE_ID`, which bound to nothing. | Two machines colliding | pydantic-settings cannot warn: an unmatched env var is indistinguishable from an unrelated one, so a typo is not an error, it is a default. |
| E4 | The ratchet written **specifically** to catch E3's class had blessed the exact broken variable — its helper accepted the bare field name, which for `node_id` is literally `NODE_ID`. | Reading it after E3 | The ratchet was green and its docstring claimed it "would have caught the original bug". |
| E5 | ROADMAP 2.7 claimed per-node mesh isolation, with passing tests. The property was **false in every deployment that sets a fleet token**, which is every real one. Fixed 2026-08-13 as W7/D9. | Reasoning about a second machine's registration | The tests were correct. The premise they encoded was wrong. |
| E6 | A check written *in the W7 session, by an agent that had just read E3 and E4*, passed cleanly against a fully reintroduced version of the bug it was written to catch. | Mutating it | It only exercised the upgrade path, where the poisoned variable is never written. |

**What is common to all six: each was found by a real machine, a real person, or a
deliberate act of sabotage against the check itself. Not one was found by the suite.**

E4 and E6 are the two that should decide the design. In both, an agent wrote a check
*for this exact failure class*, with the previous instance in front of it, and the
check could not fail. Knowing about the pattern did not prevent it. **So the answer
cannot be "be more careful" or "add a rule to CLAUDE.md" — those were already tried,
in the same session, and lost.**

## Why two agents, and why they must not be given the same material

D7 asks for a second pair of eyes and is deliberately open, because *an answer
produced by the party asking is the failure mode, not the fix*.

Two agents that both read `ROADMAP.md`, `docs/decisions/` and `docs/PREMISES.md`
will inherit the same premises and agree with each other. That agreement is worth
nothing — it is one eye, twice, and it will be confident in precisely the places the
premises are wrong. **Consensus between them is the least informative outcome
available and must not be treated as a result.**

So the two agents are given asymmetric access, and **disagreement is the deliverable.**

### Agent A — the archivist

**Reads everything.** `ROADMAP.md`, `STATUS.md`, `docs/decisions/`,
`docs/PREMISES.md`, `specs/`, `docs/historical/`, `CLAUDE.md`, `.claude/`, the git
log, and the code.

**Its question:** for each load-bearing claim this project makes, what evidence
actually exists, and *of what kind*? Classify every one by the strongest evidence
that has ever supported it:

1. asserted in prose only
2. checked by a test against a mock or a fixture
3. checked in-process against real components (a real Zenoh session on loopback)
4. exercised on a second physical machine
5. exercised across a real network boundary (NAT)

It must produce counts, not adjectives. Where a claim's evidence class is 1 or 2 and
the claim is load-bearing, that is the exposure surface.

### Agent B — the cold reader

**Must NOT read** `ROADMAP.md`, `STATUS.md`, `docs/decisions/`, `docs/PREMISES.md`,
`specs/`, `docs/historical/`, `CLAUDE.md`, `AGENTS.md`, `.claude/rules/`, or any
commit message. Those are the prose in which this project explains itself, and the
whole point of B is to see what someone gets who cannot read the explanation.

**May read:** source under `packages/`, the tests, the installers,
`docker-compose.test.yml`, config files, and `--help` output. It may run things.

**Its question:** from the artifacts alone — what does this system claim to do, what
must be true of the world for those claims to hold, and which of those can it find
any evidence for? It should state plainly where it cannot tell whether something has
ever run.

The asymmetry is the instrument. Where B derives a load-bearing assumption that A
finds written down nowhere, or A cites a premise B can find no trace of in the
artifacts, **that gap is the finding** — it is a thing believed by the project and
not present in the thing the project ships.

### The consultation

After both report independently, they exchange full findings and argue. Rules:

- **"I defer to the other agent" is not a permitted resolution.** Nor is splitting
  the difference.
- Each disagreement must end as either (a) a falsifiable statement one of them tests
  **in that session**, with output, or (b) an explicit open question naming what
  evidence would settle it and who could produce it.
- Agreement reached without either agent changing a position is recorded as
  *unexamined agreement* and flagged, not counted as consensus.
- Anything either agent proposes as a mechanism must be tested against **all six
  escapes above**. A mechanism that would not have caught E4 or E6 is not the answer,
  because those are the two that survived an agent who knew about the pattern.

## Done looks like

- [ ] `docs/decisions/D10-<name>.md` exists, recording the decision, the alternatives
      rejected **with reasons**, and an explicit "the cost, stated" section in the
      style of D9.
- [ ] D10 contains a table mapping each of E1–E6 to whether the chosen mechanism
      would have caught it, with the reasoning. Any "no" is stated as a "no", not
      argued away.
- [ ] The two agents' independent reports are preserved verbatim before the
      consultation, so a later reader can see what each thought *before* being
      influenced — including where they were wrong.
- [ ] Every disagreement is listed with its resolution class: tested-and-settled,
      or open-with-named-falsifier. No disagreement is silently dropped.
- [ ] Whatever mechanism is chosen is **implemented and mutation-tested** — broken
      deliberately, observed to fail, restored — not merely specified. E6 is the
      precedent: an unmutated check is an untested claim.
- [ ] `./scripts/verify.sh` passes, with output pasted, at a commit whose hash is
      stated.
- [ ] `docs/PREMISES.md` gains any premise the cold reader surfaced that was not
      already registered.

## Out of scope

- **Closing D7.** D7 needs a human who is not the party asking. Two agents, however
  independently configured, are still this party. If the session's output implies D7
  is closed, the session has reproduced the failure it was convened to fix.
- **The NAT test (ROADMAP 1.5, second clause).** That needs real hardware on a real
  second network and belongs to the operator.
- **Weakening any existing check to make room for a new one.** `.claude/rules/security.md`:
  if a test fails, either the code is wrong or the test is; changing the assertion to
  match broken behaviour is neither.
- **Rewriting the governance layer wholesale.** The hooks and ratchets work for the
  class they cover — regressions. This is about the class they structurally cannot
  cover. Replacing working machinery is not the ask.

## Verification

```
./scripts/verify.sh
.venv/bin/python -m pytest tests -q
```

Plus, specific to this spec: the mutation evidence for the new mechanism. The command
that breaks it, the observed failure, and the restoration — in the session's own
output.

## Notes / open questions

- **The likely shape of the answer, offered so it can be argued with rather than
  adopted.** The gate records *that* checks passed. It does not record *what kind of
  evidence* backs each claim, so "never exercised against anything real" is an
  absence, and absences are invisible. Making evidence class a generated, visible
  number would turn E1, E2 and E5 from invisible into merely bad. It is much less
  obvious that it does anything about E4 or E6, which are checks that were **present,
  green, and hollow** — and those may need something adversarial rather than
  something declarative. The two agents should attack this paragraph.
- **A mechanism that requires an agent to be diligent has already failed twice here**
  (E4, E6), in sessions that had the previous instance in front of them. Prefer
  mechanisms that make the failure loud over mechanisms that ask for care.
- This spec was written by the agent that wrote E6. That is a reason to read its
  framing sceptically, and it is stated here rather than left for someone to notice.
