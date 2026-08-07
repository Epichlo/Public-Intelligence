# Spec: Stop returning fabricated completions (ROADMAP N1)

## What this does

`POST /v1/chat/completions` can return invented text as a successful completion.
After this it answers **501 Not Implemented** for the split-inference path, and the
simulation is no longer reachable from any request.

## What actually breaks today

Verified by running it, not by reading it:

```
POST /v1/chat/completions
Authorization: Bearer <any valid RS256 JWT>
x-split-inference: true
{"model": "llama3", "messages": [{"role": "user", "content": "What is the capital of France?"}]}

→ HTTP 200
   {"choices": [{"message": {"role": "assistant", "content": "token_556"}}]}
```

Three things make this the most serious defect in the repo:

1. **It is a 200, in the standard OpenAI response shape.** Every
   OpenAI-compatible client — the official SDKs included — will surface
   `token_556` to a user as the model's answer. Nothing signals that the content is
   synthetic.
2. **Any authenticated caller can trigger it with one header.** `openai.py:101`
   accepts `req_data.split_inference`, the `x-split-inference` header, *or* a
   settings flag. No separate permission, no feature gate.
3. **The content comes from a simulation.** `LocalBoundaryEngine`
   (`openai.py:166`) is seeded `random.gauss` matrices over a toy vocabulary. It
   is not a partially-working model; it never had weights.

`CLAUDE.md` already instructs contributors not to *describe* split inference as
working. This makes the code stop *claiming* it, which is the part a user
experiences.

## Design decisions, and why

**501, not 200-with-a-warning and not 404.** 501 Not Implemented is exactly the
condition: the server recognises the request and has no implementation. A 400 would
blame the caller for asking a reasonable question. Silently ignoring the flag and
serving a real completion would be friendlier and worse — the caller asked for
split inference and would be told, in effect, that they got it.

**The execution block is deleted, not left behind the guard.** ~245 lines
(`openai.py:107–353`) become unreachable the moment the guard returns. Dead code
behind a disabled flag is how this got here: something written to be finished later,
that quietly stayed wired to the request path. Deleting it means re-enabling split
inference requires writing it, not flipping a boolean.

**`LocalBoundaryEngine` and the pipeline modules are NOT deleted here.** They are
~2,850 lines with 40-odd test files (ROADMAP C2). Removing the *reachability* is
this change; quarantining the *code* is the next one, and mixing them would make a
security fix hostage to a refactor.

**`ChatCompletionRequest.split_inference` stays in the model.** Removing the field
would make the request 422 on an unknown key rather than 501, which is a worse
answer: 422 says "malformed", 501 says "understood, not available". The field's
description now says so.

**CORRECTION — `enable_split_inference` is not a setting and never was.** This
spec first said the flag "keeps working, as a way to get 501s". Writing the test
disproved it: `Settings` has no such field, so
`getattr(get_settings(), "enable_split_inference", False)` was permanently `False`
and an operator setting `SCHEDULER_ENABLE_SPLIT_INFERENCE` got nothing, silently.
A third trigger that never fired. The `getattr` is kept in the new guard so that if
anyone ever adds the field it refuses rather than fabricates, and a test now pins
that the field is absent so the claim cannot drift back.

## Done looks like

- [x] A request with `x-split-inference: true` returns **501**, and the body names
      split inference as unimplemented. Covered by a test.
- [x] A request with `"split_inference": true` in the body returns 501. Test.
- [x] The `enable_split_inference` trigger is pinned as **dead** — `Settings` has
      no such field, so it never fired. (This box originally said it "returns 501";
      corrected when the test showed the setting does not exist.)
- [x] **No response body on any path contains `LocalBoundaryEngine` output.**
      Covered by a test that greps the module for the `token_` prefix its
      detokeniser emits and asserts no endpoint can produce it.
- [x] An ordinary (non-split) request is unaffected — same status, same dispatch.
      Covered by the existing gateway tests continuing to pass.
- [x] `openai.py` no longer imports `LocalBoundaryEngine` or the tensor transport
      helpers used only by that block. Verified by grep in the gate.
- [x] `./scripts/verify.sh` passes.

## Out of scope

- **Deleting the simulation modules** — `local_boundary`, `transport`, `kv_cache`,
  `quantization`, `engine`'s split-pipeline methods. ROADMAP C2.
- **Implementing split inference.** It is cut from v1 and is a rewrite, not a fix.
- **The five test files that exercise the removed path.** Two call the endpoint and
  are rewritten here; three (`test_kv_cache_checkpointing`, `test_speculative_fp8`,
  `test_split_pipeline_scheduling`) test the modules directly, never touch the
  endpoint, and are left for C2.

## Verification

```
./scripts/verify.sh
.venv/bin/python -m pytest packages/scheduler/tests/test_split_inference_refused.py -q
grep -n "LocalBoundaryEngine" packages/scheduler/src/scheduler/api/openai.py   # expect no hits
```

## Notes / open questions

- Duplicate-module check: `openai.py` exists only in `packages/scheduler`. The
  `transport.py` import being dropped here does not change either copy of that
  duplicated pair.
- This was found by an audit, not by a test, and no test could have found it —
  the suite asserted the split path returned *something*, never that what it
  returned was real. Worth remembering when reading a green suite: coverage of a
  path is not evidence the path should exist.
