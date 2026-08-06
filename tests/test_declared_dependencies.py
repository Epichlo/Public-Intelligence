"""Every third-party module a package imports must be in its `dependencies`.

The root `.venv` installs both packages together, so an import satisfied by the
*other* package's dependency tree resolves fine in development and in every test
suite. It does not resolve for a host who installs one package on its own.

That is not hypothetical. `node/api/auth.py` imported `structlog` while
`packages/node/pyproject.toml` did not declare it -- the scheduler declares it, so
the shared venv always had it. 280 node tests passed. A real `pip install -e
packages/node` into a clean venv produced a node that raised
`ModuleNotFoundError: No module named 'structlog'` on `import node.main`. Found by
`scripts/verify_install.sh` on its first real run; this test is the cheap ratchet
that keeps it from recurring without paying for a full install.

See specs/installer-actually-installs.md.
"""

import ast
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
STDLIB = set(sys.stdlib_module_names)

# Import name -> distribution name, where they differ.
DISTRIBUTION_NAME = {
    "zenoh": "eclipse-zenoh",
    "dotenv": "python-dotenv",
    "jwt": "pyjwt",
    "pydantic_settings": "pydantic-settings",
    "yaml": "pyyaml",
}

# First-party, so never a declared dependency. `shared` and `src` are the
# in-tree artifact-store copies the monorepo migration left behind.
FIRST_PARTY = {"node", "scheduler", "shared", "src"}


def declared_dependencies(package: str) -> set[str]:
    """Distribution names in a package's `[project].dependencies`.

    Parsed with `tomllib` rather than by splitting text. A hand-rolled parser
    written for this check split on `]` and silently truncated the scheduler's list
    at `uvicorn[standard]`, reporting six false positives -- so the real state was
    briefly hidden behind a broken measurement of it.
    """
    data = tomllib.loads(
        (REPO_ROOT / "packages" / package / "pyproject.toml").read_text(encoding="utf-8")
    )
    return {
        spec.split(">")[0].split("<")[0].split("=")[0].split("[")[0].strip().lower()
        for spec in data["project"]["dependencies"]
    }


def imported_modules(package: str) -> dict[str, str]:
    """Third-party top-level modules imported under a package's `src`, with a site.

    Only absolute imports at module scope or inside functions -- both matter, since
    a function-level import still fails at call time on a host that lacks it.
    """
    found: dict[str, str] = {}
    for path in (REPO_ROOT / "packages" / package / "src").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".")[0]]
            for name in names:
                if name in STDLIB or name in FIRST_PARTY:
                    continue
                found.setdefault(name, f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
    return found


@pytest.mark.parametrize("package", ["node", "scheduler"])
def test_every_imported_third_party_module_is_declared(package: str) -> None:
    """A package installed on its own must be able to import itself."""
    declared = declared_dependencies(package)
    undeclared = {
        name: site
        for name, site in imported_modules(package).items()
        if DISTRIBUTION_NAME.get(name, name) not in declared
    }

    assert not undeclared, (
        f"packages/{package} imports modules it does not declare as dependencies. "
        f"These resolve in the shared dev venv and will not resolve for a host who "
        f"installs this package alone: {undeclared}"
    )
