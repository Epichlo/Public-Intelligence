"""Code the Node and the Scheduler must agree on byte for byte.

See `packages/shared/README.md` for what belongs here and what does not. The short
version: a module lives here when the two services disagreeing about it fails
SILENTLY. Mesh envelopes are the case that matters -- if `mesh_auth` drifts, the
Scheduler stops accepting real nodes and nothing raises.
"""
