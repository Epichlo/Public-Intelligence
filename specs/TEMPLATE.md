# Spec: <feature name>

> Copy this file to `specs/<feature-name>.md` and fill it in **before** writing code.
> Delete the italic prompts as you go. If a section is hard to fill in, that is
> signal the feature isn't understood yet — not a reason to skip the section.

## What this does

*2-3 sentences, plain language. What changes for a user or an operator once this
exists? Write it as if explaining to someone who has not read the codebase.*

## Done looks like

*A short, concrete, checkable list. Every line must be something a person can
verify by running a command or reading a specific file — not a feeling.*
*Bad: "split inference works reliably."*
*Good: "`POST /v1/chat/completions` with `split: true` returns a 503 (not a 500)
when no node is registered — covered by a test in `Scheduler/tests/`."*

- [ ]
- [ ]
- [ ]

## Out of scope

*What this feature explicitly does NOT do. Be specific — this is the section that
stops scope creep and stops a later reader assuming more was built than was.*
*If something here is a known gap rather than a deliberate exclusion, say which.*

-
-

## Verification

*How a reviewer confirms the "Done looks like" list. Name the exact commands.*
*This is checked against `VERIFY.md` step 2.*

```
# e.g.
Scheduler/.venv/bin/python -m pytest Scheduler/tests -q
```

## Notes / open questions

*Anything unresolved. An open question written down is fine; an open question
silently assumed is not.*

-
