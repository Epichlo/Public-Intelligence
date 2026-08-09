"""Compatibility import for the canonical local boundary engine."""

# Sibling import: `scheduler.core.local_boundary` moved here under ROADMAP C2 and no
# longer exists. This shim pointed at it and was therefore unimportable.
from experimental.scheduler.local_boundary import LocalBoundaryEngine

__all__ = ["LocalBoundaryEngine"]
