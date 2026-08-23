# packages/shared

**Archived on 2026-08-21 along with the rest of the project. See the root
[`README.md`](../../README.md) for what worked, what failed, and why it stopped.**

The stated follow-up to the 2026-08-04 monorepo migration (ROADMAP C8), and the
answer to the question `CLAUDE.md` has been asking contributors to hold in their
heads: *"before adding a module, check whether its twin exists; if you change one of
a pair, change both."*

That instruction works exactly as well as the person reading it remembers it. This
directory removes the need to remember.

## What belongs here

Code the Node and the Scheduler must agree on **byte for byte**, where a
disagreement is silent rather than loud. Today that is the mesh protocol: if the two
copies of `mesh_auth` drift, the Scheduler stops accepting envelopes from real
nodes — and nothing raises, the fleet just goes quiet.

## What does not

Anything merely *similar*. Two modules that happen to look alike are not a shared
module; they are two modules. Pulling those in here couples two services so that a
change wanted by one is forced on the other, which is a worse problem than the
duplication.

`packages/node/src/node/storage/` is the example: it was a third copy of an artifact
store, and the right fix was deleting two of them (C8), not sharing one.

## Why `pi_shared` and not `shared`

`packages/node/src/shared/` used to install a top-level `shared` package into
site-packages, so any other distribution shipping that name collided with it. The
prefix is not decoration.
