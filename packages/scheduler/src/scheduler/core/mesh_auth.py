"""Re-export of `pi_shared.mesh_auth` (ROADMAP C8).

This module used to be one of two byte-identical copies, one per service, held in
step by a drift ratchet and by `CLAUDE.md` asking contributors to remember to
change both. The single copy now lives in `packages/shared`; this file exists so
the ~30 existing `scheduler.core.mesh_auth` import sites did not all have to move in the same
change that moved the code.

Import `pi_shared.mesh_auth` directly in new code.
"""

from pi_shared.mesh_auth import *  # noqa: F403
from pi_shared.mesh_auth import __all__ as __all__
