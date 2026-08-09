#!/usr/bin/env python3
"""Issue, list and revoke node invite codes (decision D4).

An invite code is what a host presents at `POST /nodes/register`. Registration used
to be gated by the fleet-wide `SCHEDULER_NETWORK_AUTH_TOKEN` alone, which admits but
records nothing: "who vouched for this host" was unanswerable, and removing one host
meant rotating the secret for all of them.

    scripts/mint_invite.py --issue --label "alice's workstation"
    scripts/mint_invite.py --issue --label "the lab" --max-uses 4
    scripts/mint_invite.py --list
    scripts/mint_invite.py --revoke <code>

**The code is shown once.** Only its SHA-256 is stored, for the same reason a
password hash is: the database should not leak admission.

This talks to the store directly rather than to a running Scheduler, so it works
before the service is up and does not need an HTTP surface that could itself be
attacked. It therefore needs the same `SCHEDULER_DATABASE_PATH` the Scheduler uses.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages/scheduler/src"))

from scheduler.core.config import get_settings
from scheduler.core.invites import InviteRegistry
from scheduler.persistence import SQLiteStore


async def _registry() -> InviteRegistry:
    settings = get_settings()
    if not settings.database_path:
        print(
            "SCHEDULER_DATABASE_PATH is empty, so invites cannot be persisted.\n"
            "An invite that does not survive a restart is not admission control.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    registry = InviteRegistry(store=SQLiteStore(settings.database_path))
    await registry.load()
    return registry


async def _run(args: argparse.Namespace) -> int:
    registry = await _registry()

    if args.issue:
        code, invite = await registry.issue(label=args.label, max_uses=args.max_uses)
        print("Invite code (shown once -- only its hash is stored):\n")
        print(f"    {code}\n")
        print(f"  label:    {invite.label or '(none)'}")
        print(f"  max uses: {invite.max_uses}")
        print("\nThe host sets this in packages/node/.env:")
        print(f"    NODE_INVITE_CODE={code}")
        return 0

    if args.revoke:
        changed = await registry.revoke(args.revoke)
        # Reports whether anything CHANGED, matching how ROADMAP 2.5 made eviction
        # report: "already revoked" and "revoked just now" are different facts.
        print("revoked" if changed else "no change -- unknown or already revoked")
        return 0 if changed else 1

    rows = registry.summary()
    if not rows:
        print("No invites issued. Registration is OPEN to anyone holding the fleet token.")
        return 0
    print(f"{'LABEL':30} {'USES':>8}  {'STATE':10}")
    for row in rows:
        state = "revoked" if row["revoked"] else ("usable" if row["usable"] else "spent")
        uses = f"{row['uses']}/{row['max_uses']}"
        print(f"{row['label'] or '(none)'!s:30} {uses:>8}  {state:10}")
    return 0


def main() -> int:
    """Parse arguments and dispatch."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--issue", action="store_true", help="create a new invite code")
    parser.add_argument("--label", default="", help="operator note: who this is for")
    parser.add_argument("--max-uses", type=int, default=1, help="nodes this code may admit")
    parser.add_argument("--revoke", metavar="CODE", help="stop future use of a code")
    parser.add_argument("--list", action="store_true", help="show issued invites (default)")
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
