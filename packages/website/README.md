# Public Intelligence Website

**Archived on 2026-08-21 along with the rest of the project. See the root
[`README.md`](../../README.md) for what worked, what failed, and why it stopped.**

The Next.js front end for **Public Intelligence**: a dashboard over a running Scheduler,
an interactive playground against its OpenAI-compatible gateway, and the public pages
that describe the project.

Part of the **`public-intelligence` monorepo** (the Scheduler, Node and Website were
merged into `packages/` on 2026-08-04). This document describes `packages/website`.

> **This README described the project as "a globally distributed, community-owned AI
> infrastructure" until 2026-08-21.** That was never true and had been explicitly decided
> against: [D6](../../docs/decisions/D6-is-there-a-network.md) records that there is no
> network and one will not be operated, and [D2](../../docs/decisions/D2-economics.md)
> that the marketplace economics do not close. The site's own landing page
> (`src/components/landing/unredacted-truth.tsx`) had been corrected; this file had not.
> It is fixed here because a stale README is how a claim outlives the decision that
> retired it.

---

## Pages

Nine routes under `src/app`:

| Route | What it does |
|---|---|
| `/` | Landing page, including the "Unredacted Truth" panel listing what is and is not proven |
| `/dashboard` | Live view of registered nodes, telemetry and credit, proxied to the Scheduler |
| `/playground` | Interactive chat against `/v1/chat/completions`, with a bearer token you supply |
| `/status` | Fleet and request status |
| `/vision`, `/architecture`, `/research`, `/roadmap`, `/contribute` | Static project pages |

`/dashboard`, `/playground` and `/status` are the functional ones — they proxy to a
running Scheduler and do nothing useful without one. The earlier version of this file
listed only the five static pages and omitted all three.

## Tech stack

- Next.js 16 / React 19
- TypeScript
- Tailwind CSS

## Development

```bash
npm install
npm run dev     # http://localhost:3000
```

The dashboard and playground need a Scheduler to talk to; see
[`packages/scheduler`](../scheduler/README.md).

## Version

`package.json` declares **`1.0.0`**. The last release tag is **`v1.0.1`** — the two do not
match, and that discrepancy is recorded rather than papered over in the root
[`README.md`](../../README.md) ("A ratchet that cannot see the thing it names"). The
version-parity ratchet compares the four packages to each other, never to the tag.

## Related components

Part of the `public-intelligence` monorepo, alongside `packages/scheduler` (control
plane), `packages/node` (host agent) and `packages/shared`. They are directories, not
separate repositories — the pre-monorepo standalone repos are archived and tagged
`pre-monorepo-2026-08-04`.

## Licence

Apache 2.0
