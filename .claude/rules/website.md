---
description: Dashboard and playground rules for packages/website
paths: ["packages/website/**"]
---

# packages/website — dashboard and playground

Next.js 16 / React 19. Every browser fetch goes to a same-origin Next.js route that
reaches the services server-side; the browser never holds a service credential.

- **The language is the product decision.** Credits are *contributed*, never
  *earned* — D2 cut redemption, so a currency symbol in this UI is a false claim
  about the product, not a formatting choice. `formatCredits` has a test asserting
  exactly that.
- **Never render uncertainty as zero.** An unreachable Scheduler is "unavailable",
  not "0 contributed". A node that has served nothing shows `—` for its failure rate,
  not a healthy-looking 0%. Both distinctions are tested.
- **Never claim a capability the system does not have.** This site said "The core
  distributed infrastructure is realized" while no node on a separate machine had
  ever served a request. Landing-page copy is a claim; check it against `ROADMAP.md`.
- **Windowed totals are labelled as windowed.** A figure read as all-time that
  silently resets when a buffer wraps is worse than no figure.
- **The SSE parser is the one place where wrong is invisible** — a dropped delta
  reads as the model not saying that word. It lives in `lib/sse.ts`, extracted from
  React state handling precisely so it can be tested; keep it there and keep it pure.

`npm run lint`, `npm run typecheck`, and `npm test` all run inside
`./scripts/verify.sh`. eslint is not a type-checker: pointing `tsc` at this tree
found four errors eslint had passed clean.
