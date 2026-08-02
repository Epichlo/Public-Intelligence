---
name: test-first
description: Use when writing, changing, or fixing any code with test coverage available - new functions, endpoints, bug fixes, refactors. Enforces writing a failing test before the implementation and observing it fail, then pass. Triggers on - "implement", "add a feature", "fix this bug", "write a function", "add an endpoint", or any request that produces new behaviour in Node/, Scheduler/, or website/.
---

# Test first

Write the test before the code. Watch it fail. Then make it pass.

The reason is narrow and practical: **a test you never saw fail has proven nothing.**
It may be asserting something trivially true, exercising the wrong path, or silently
passing on an exception you swallowed. Observing red → green is what converts a test
from decoration into evidence.

## The loop

**1. Red — write the failing test first**

```bash
Node/.venv/bin/python -m pytest Node/tests/test_thing.py::test_new_behaviour -q
```

You must see it **fail**, for the right reason. A test that errors on an import
typo is not red — it is broken. Read the failure and confirm it is the assertion
you intended.

**2. Green — write the minimum code to pass**

Just enough. Don't build the general case while the specific one isn't passing yet.

**3. Confirm — rerun, then run the whole suite**

```bash
Node/.venv/bin/python -m pytest Node/tests/test_thing.py::test_new_behaviour -q  # targeted
Node/.venv/bin/python -m pytest Node/tests -q                                    # no regressions
```

**4. Refactor** — only once green, with the suite as your safety net.

## Where tests go

| Change is in | Test goes in | Interpreter |
|---|---|---|
| `Scheduler/src/` | `Scheduler/tests/` | `Scheduler/.venv/bin/python` |
| `Node/src/` | `Node/tests/` | `Node/.venv/bin/python` |
| spans both | `tests/` (root E2E) | `Node/.venv/bin/python` |
| `website/src/` | **no harness exists** — see below | — |

The root suite runs only under `Node/.venv`; it is the sole environment with both
`node` and `scheduler` importable.

**`website/` has zero test infrastructure.** No runner, no test files. If you change
the playground, proxy routes, or SSE parsing, you cannot write a test without first
setting up a harness. Say so explicitly rather than shipping untested and quietly
implying otherwise.

## What a real test looks like here

Assert on **behaviour**, not on the shape of your own mock.

```python
# Weak: passes whether or not the endpoint works
mock_engine.schedule.return_value = ["stage"]
assert mock_engine.schedule.called

# Real: asserts the contract a caller depends on
response = client.post("/v1/chat/completions", json={...}, headers=auth)
assert response.status_code == 503
assert "No suitable compute nodes" in response.json()["detail"]
```

Be honest about what a mock proves. This repo runs 157 Node tests in under 3 seconds
across "split inference", "KV cache", and "end-to-end pipeline" — none of which touch
a network or a model. That is fine as unit testing, and it is **not** evidence that
distributed inference works. Don't let a fast green suite stand in for integration
you haven't done.

## Bug fixes

Reproduce first, always:

1. Write a test that fails **because of the bug**.
2. Confirm it fails against the unfixed code.
3. Fix.
4. Confirm it passes.

A fix with no reproducing test can silently regress, and you have no way to tell
whether you fixed the bug or merely moved it.

## When you skip this

Sometimes justified — a one-line doc change, a config value with no logic. When you
skip, **say you skipped and why**. Don't let "no test needed" be a silent default;
that is how the untested paths in this repo accumulated.

## Then verify

Passing tests are one line of `VERIFY.md`, not the whole of it. Run the full
checklist as a separate pass before calling anything done.
