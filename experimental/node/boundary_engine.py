"""Local Boundary Isolation Engine for Layer 0 and Layer N."""

# Sibling import: `node.core.local_boundary` moved here under ROADMAP C2 and no
# longer exists. This shim pointed at it and was therefore unimportable.
from experimental.node.local_boundary import LocalBoundaryEngine

__all__ = ["LocalBoundaryEngine"]
