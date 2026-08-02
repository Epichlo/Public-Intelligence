#!/usr/bin/env python3
"""Generate the RS256 keypair and mint tenant JWTs for the Scheduler gateway.

The Scheduler verifies bearer tokens with `jwt.decode(..., algorithms=["RS256"])`
against the public key in `app.state.jwt_public_key`, falling back to the
`JWT_PUBLIC_KEY` environment variable. This script produces a matching keypair
and signs tokens with the private half.

Replaces the removed `dev_*` bypass -- see specs/remove-dev-token-bypass.md.

Generate a keypair (once):

    python3 scripts/mint_token.py --generate-keypair

Mint a token for a tenant:

    python3 scripts/mint_token.py --tenant tenant-a --hours 24

Deploy: set JWT_PUBLIC_KEY on the Scheduler to the contents of the public key
file. Keep the private key off the server -- it only signs tokens.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ROOT = Path(__file__).resolve().parent.parent
KEY_DIR = ROOT / ".secrets"
PRIVATE_KEY = KEY_DIR / "jwt_private_key.pem"
PUBLIC_KEY = KEY_DIR / "jwt_public_key.pem"


def generate_keypair(force: bool = False) -> None:
    """Create a 2048-bit RSA keypair for RS256 token signing."""
    if PRIVATE_KEY.exists() and not force:
        print(
            f"Refusing to overwrite existing key at {PRIVATE_KEY.relative_to(ROOT)}.\n"
            "Re-run with --force if you really mean to rotate (this invalidates "
            "every token already issued).",
            file=sys.stderr,
        )
        raise SystemExit(1)

    KEY_DIR.mkdir(parents=True, exist_ok=True)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    PRIVATE_KEY.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    PRIVATE_KEY.chmod(0o600)

    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    PUBLIC_KEY.write_bytes(public_pem)
    PUBLIC_KEY.chmod(0o644)

    print(f"Private key -> {PRIVATE_KEY.relative_to(ROOT)} (mode 600, keep secret)")
    print(f"Public key  -> {PUBLIC_KEY.relative_to(ROOT)}")
    print("\nSet this as JWT_PUBLIC_KEY on the Scheduler:\n")
    print(public_pem.decode("utf-8"))


def mint(tenant: str, subject: str, hours: int) -> str:
    """Sign an RS256 JWT carrying the tenant claim the gateway requires."""
    if not PRIVATE_KEY.exists():
        print(
            f"No private key at {PRIVATE_KEY.relative_to(ROOT)}.\n"
            "Run: python3 scripts/mint_token.py --generate-keypair",
            file=sys.stderr,
        )
        raise SystemExit(1)

    private_key = serialization.load_pem_private_key(
        PRIVATE_KEY.read_bytes(), password=None
    )

    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": subject,
            "tenant_id": tenant,  # required -- gateway 401s without it
            "iat": now,
            "exp": now + timedelta(hours=hours),
        },
        private_key,  # type: ignore[arg-type]
        algorithm="RS256",
    )


def main() -> int:
    """Parse arguments and dispatch."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--generate-keypair", action="store_true", help="create a new RS256 keypair"
    )
    parser.add_argument(
        "--force", action="store_true", help="overwrite an existing keypair"
    )
    parser.add_argument("--tenant", default="tenant-a", help="tenant_id claim")
    parser.add_argument("--subject", default="playground-user", help="sub claim")
    parser.add_argument("--hours", type=int, default=24, help="token lifetime")
    args = parser.parse_args()

    if args.generate_keypair:
        generate_keypair(force=args.force)
        return 0

    token = mint(args.tenant, args.subject, args.hours)
    print(token)
    print(
        f"\n# tenant={args.tenant} expires in {args.hours}h\n"
        f'# curl -H "Authorization: Bearer {token[:24]}..." '
        "http://localhost:8000/v1/chat/completions",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
