# Spec: Collapse the submodules into a monorepo

## What this does

`Public-Intelligence` is four git repositories: a workspace that stores commit
pointers, plus `Node`, `Scheduler`, and `website` as submodules. After this it is
one repository containing all of them under `packages/`.

Nothing about how the services build, run, or deploy changes. What changes is that
one logical change becomes one commit instead of three in dependency order, and
`packages/shared/` becomes possible — which is the only reason the six duplicated
module pairs exist.

Concretely, today: roadmap 1.3 took three commits across three repos, and 17
commits were spread across three histories in one session.

## Done looks like

- [ ] One git repository. `git submodule status` is empty, `.gitmodules` is gone.
- [ ] `packages/node`, `packages/scheduler`, `packages/website` exist, each with the
      **full commit history** of its old repo reachable via `git log --follow`.
      History-preserving subtree merges, not file copies.
- [ ] One virtualenv at the repo root replaces the three. The root E2E suite no
      longer depends on being run under `Node/.venv` specifically.
- [ ] `./scripts/verify.sh` passes, with the same checks it has today.
- [ ] CI passes on all 9 matrix legs plus fresh-clone, with `submodules: recursive`
      removed from the checkout.
- [ ] The three GitHub repos are left intact and still hold `pre-monorepo-2026-08-04`.
      Nothing is deleted; archiving them is a separate, later decision.
- [ ] Test counts are unchanged or higher: 218 Scheduler / 243 Node / 53 root.

## Out of scope

- **Deduplicating the six copied module pairs into `packages/shared/` is a SEPARATE
  change**, done immediately after this one. Combining a structural move with a
  code change would make a failure impossible to attribute. This spec only makes
  `shared/` *possible*.
- **The website is moved, not otherwise touched.** It still has zero tests.
- Archiving or deleting the old GitHub repos — the user's call, later.
- Any change to what the services do at runtime.

## Verification

```
./scripts/verify.sh
git log --oneline -- packages/node | wc -l      # must show pre-migration history
gh run list --limit 1
```

## Notes / open questions

- **Rollback:** every repo is tagged `pre-monorepo-2026-08-04` and pushed. The three
  submodule repos remain untouched on GitHub, so the old layout is fully
  reconstructible even after this lands.
- The three `.venv` directories are not tracked; they are rebuilt, not migrated.
- `git log --follow` across the move works per-file; plain `git log <path>` shows
  history from the merge point onward. Both old repos remain the authoritative
  record of pre-migration history regardless.
- The pre-push hook currently runs the full gate on tag-only pushes, which is
  pointless and slow. Fixed as part of this change since it was hit while tagging.
