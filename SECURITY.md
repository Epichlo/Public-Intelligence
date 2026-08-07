# Security Policy

## Reporting a vulnerability

**Do not open a public issue for a security problem.**

Report it privately through GitHub's advisory flow:

<https://github.com/Epichlo/Public-Intelligence/security/advisories/new>

If that is not available to you, email **atharvdesh200713@gmail.com** with
`SECURITY` in the subject.

Please include what you can — affected file and line, the version or commit, what an
attacker gains, and a way to reproduce it. A rough report is more useful than none;
do not sit on something because it is not written up.

### What to expect

This is a **pre-alpha project maintained by one person**. There is no security team
and no on-call. Setting expectations honestly rather than copying a template:

| | |
|---|---|
| Acknowledgement | within 7 days |
| Assessment | within 30 days |
| Fix or a stated decision not to fix | best effort, no guarantee |

You will be credited unless you ask not to be. There is no bounty programme.

## Scope

**In scope** — anything in `packages/scheduler`, `packages/node`,
`packages/website`, the installers (`install.sh`, `install.ps1`), and the gate
scripts under `scripts/`.

**Out of scope** — `docs/historical/`: superseded documents, kept as history, not
shipped code.

Code for features cut from v1 (split inference, Raft consensus, KV-cache
checkpointing) is currently still inside `packages/` and **is in scope** while it
sits there. ROADMAP C2 moves it to `experimental/`; once it has moved, reaching it
from a running Scheduler or node is *itself* the vulnerability, because it is
supposed to be unreachable.

## Known unfixed issues

This project keeps its known weaknesses in the open rather than in a private tracker.
`VERIFY.md` step 3 lists the auth bypasses and default credentials present in the
tree, with `file:line`. They are pre-existing, tracked in `ROADMAP.md`, and **not**
things you need to report.

Anything *not* on that list is worth reporting.

## Supported versions

There are no releases yet. `main` is the only supported version. When there are
releases, this table gets filled in rather than deleted.

## Operating this software

Running a node or a coordinator carries risks that are not vulnerabilities in the
code — you become the egress point for generated content, prompts you serve are other
people's data, and Zenoh mesh links are plaintext unless you configure TLS. Those are
documented in `docs/OPERATING.md`, which ships with the invite-code admission work
(ROADMAP D4) and which you should read before running this for anyone but yourself.
