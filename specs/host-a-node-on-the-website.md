# Spec: the hosting command is on the website

## What this does

The one-line command that installs and starts a host node exists in `README.md` and in
`scripts/bootstrap.sh`'s own header, and nowhere a visitor to the site can see it. The
landing page tells someone what the project is and links them to the source; it never
tells them how to put a machine into their own fleet. This puts that command on the
landing page, with a copy button, and ties the displayed string to the one the README
documents so the two cannot drift apart.

The command is rendered as **the string that is actually run**. It is not a "join the
network" call to action: per [D6](../docs/decisions/D6-is-there-a-network.md) there is
no network to join and no operated Scheduler, so the placeholders
(`https://your-scheduler`, `TOKEN`, `CODE`) stay visibly placeholders and the copy
around the block says the operator supplies them.

## Done looks like

- [ ] `packages/website/src/lib/host-command.ts` exports `HOST_NODE_COMMAND`, a plain
      string, with no React import — so it is testable under `environment: "node"`.
- [ ] `HOST_NODE_COMMAND` is byte-identical to the bash block under `## Host a node` in
      the repository `README.md`. Enforced by a test that reads `README.md` off disk and
      fails if either side is edited alone.
- [ ] The command names `scripts/bootstrap.sh` on the `Epichlo/Public-Intelligence`
      raw URL and carries all three flags `bootstrap.sh` forwards to `install.sh`
      (`--scheduler-url`, `--fleet-token`, `--invite-code`). Each asserted separately,
      so a parity test passing vacuously against two identically-wrong strings fails.
- [ ] A test asserts the string contains **no** real hostname in the
      `--scheduler-url` position — it must stay `https://your-scheduler`. A copied
      command that silently points at someone else's machine is the failure mode.
- [ ] `packages/website/src/components/landing/host-a-node.tsx` renders the block and a
      copy button, and is reachable from `/` (imported by `src/app/page.tsx`).
- [ ] `./scripts/verify.sh` passes, including `npm run lint`, `npm run typecheck` and
      `npm test` for the website.

## Out of scope

- **Rendering tests for the component.** `vitest.config.mts` sets
  `environment: "node"` deliberately; a component test needs jsdom, which this project
  does not install. This is why the command string lives in `lib/` and the component is
  a thin wrapper around it — the same split `contribution-summary.ts` and `lib/sse.ts`
  already use. It is a known gap, not a claim that the button is tested.
- **Deploying the website.** There is no `vercel.json`, no `netlify.toml` and no
  registered domain (D6). This change puts the command in the page source; it does not
  put the page on the internet.
- **Any change to `bootstrap.sh`, `install.sh` or the flags themselves.**
- **The clipboard fallback.** `navigator.clipboard` is absent on insecure origins; the
  block is selectable text, so the fallback is "select it yourself". No polyfill.

## Verification

```
./scripts/verify.sh
```

Website-only tight loop:

```
cd packages/website && npm run lint && npm run typecheck && npm test
```

The parity test specifically:

```
cd packages/website && npx vitest run src/lib/host-command.test.ts
```

## Notes / open questions

- The parity test reads `README.md` through a path relative to the test file rather
  than to `process.cwd()`, because the gate invokes the website suite from the package
  directory and a developer may invoke it from the repo root.
- `README.md` is outside the website package. That is the point — the drift this test
  exists to catch is precisely between the docs and the site. If the website package is
  ever built in isolation without the repo around it, this test fails loudly rather
  than silently skipping, which is the correct direction to fail.
