"""Every env var in docker-compose.test.yml must be one the services actually read.

ROADMAP 1.5's specific complaint: the compose file "has never run and its `NODE_ID`
env var is wrong (needs `NODE_NODE_ID`)". A node reading `NODE_ID` silently kept its
default id, so both workers would have collided -- and nothing would have said so,
because a pydantic-settings field simply does not see an env var that does not match
its alias.

**This does not run the compose file.** Docker is not available in every environment
that runs this gate, and pretending otherwise by mocking it away would be worse than
skipping. What it does is close the *class* of defect 1.5 named: a typo'd variable
that is silently ignored. That is checkable statically, cheap, and would have caught
the original bug.

What is still NOT verified by anything, and is the load-bearing claim of the whole
project (`docs/PREMISES.md` P2, `docs/decisions/D8-the-wedge.md`): **two containers,
let alone two machines, have never actually exchanged an inference request.** 1.5
stays partial until someone runs it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic_settings import BaseSettings

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPOSE = REPO_ROOT / "docker-compose.test.yml"

# Env vars consumed by something other than a Settings model.
NOT_SETTINGS_FIELDS = {
    # Read by uvicorn / the container entrypoint rather than by pydantic.
    "PYTHONUNBUFFERED",
    "PATH",
}


def _compose_env() -> dict[str, list[str]]:
    """Environment variable names per service, parsed without a YAML dependency.

    Neither package depends on PyYAML and adding one for a single test would be a
    dependency the shipped services carry for a check. The file's shape is known and
    stable: `- NAME=value` under an `environment:` block.
    """
    text = COMPOSE.read_text(encoding="utf-8")
    services: dict[str, list[str]] = {}
    current: str | None = None
    in_env = False

    for raw in text.splitlines():
        line = raw.rstrip()
        if re.match(r"^  [a-z0-9_-]+:$", line):
            current = line.strip().rstrip(":")
            services.setdefault(current, [])
            in_env = False
        elif re.match(r"^    environment:$", line):
            in_env = True
        elif in_env and re.match(r"^      - [A-Z]", line):
            name = line.strip().lstrip("- ").split("=", 1)[0]
            if current:
                services[current].append(name)
        elif in_env and line and not line.startswith("      "):
            in_env = False
    return services


def _accepted_names(settings_cls: type[BaseSettings]) -> set[str]:
    """Every env var name a pydantic-settings model will actually read.

    Includes the `env_prefix` form and every `AliasChoices` entry, because both are
    live and a reader of the compose file cannot tell which is which.
    """
    prefix = settings_cls.model_config.get("env_prefix", "") or ""
    names: set[str] = set()

    for field_name, field in settings_cls.model_fields.items():
        names.add(f"{prefix}{field_name}".upper())
        names.add(field_name.upper())
        alias = field.validation_alias
        if alias is None:
            continue
        if isinstance(alias, str):
            names.add(alias.upper())
        else:  # AliasChoices
            for choice in getattr(alias, "choices", []):
                if isinstance(choice, str):
                    names.add(choice.upper())
    return names


@pytest.mark.parametrize(
    ("service_prefix", "import_path"),
    [
        ("node-worker", "node.core.configuration:Settings"),
        ("scheduler", "scheduler.core.config:Settings"),
    ],
)
def test_every_compose_env_var_is_read_by_its_service(
    service_prefix: str, import_path: str
) -> None:
    """A variable the service does not read is a setting that silently does nothing."""
    import importlib

    module_name, class_name = import_path.split(":")
    settings_cls: type[BaseSettings] = getattr(importlib.import_module(module_name), class_name)
    accepted = _accepted_names(settings_cls)

    unread: dict[str, list[str]] = {}
    for service, names in _compose_env().items():
        if not service.startswith(service_prefix):
            continue
        missed = [n for n in names if n not in accepted and n not in NOT_SETTINGS_FIELDS]
        if missed:
            unread[service] = missed

    assert not unread, (
        f"docker-compose.test.yml sets variables {service_prefix} services do not "
        f"read: {unread}. pydantic-settings ignores an unmatched name silently, so "
        f"the service keeps its default and nothing reports it -- which is exactly "
        f"how NODE_ID sat there instead of NODE_NODE_ID (ROADMAP 1.5)."
    )


def test_the_compose_file_configures_a_gateway_key() -> None:
    """Since ROADMAP C4 an unconfigured gateway refuses every request.

    That is the correct default, and it means this compose file -- which exists so a
    person can send a request through it -- must set a key or it demonstrates
    nothing but 401s.
    """
    text = COMPOSE.read_text(encoding="utf-8")
    assert "JWT_PUBLIC_KEY" in text, (
        "docker-compose.test.yml sets no JWT public key, so /v1/chat/completions "
        "refuses everyone (ROADMAP C4) and the two-node demo cannot serve a request."
    )


def test_the_compose_file_does_not_reference_removed_settings() -> None:
    """A comment describing a setting that no longer exists is a trap for a reader.

    `TELEMETRY_SECRET_KEY` was removed by ROADMAP 2.7 -- mesh envelopes are keyed on
    each node's own credential now. A file telling an operator both services must
    agree on it describes a system that has not existed for several commits.
    """
    # Comments are stripped. A comment saying "TELEMETRY_SECRET_KEY no longer
    # exists" is the correct thing to have; only a live setting is the trap. This
    # test failed on its own explanation the first time it ran, which is the fourth
    # instance of that pattern in this change set and the reason it is worth naming.
    config = "\n".join(
        line
        for line in COMPOSE.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )
    for removed in ("TELEMETRY_SECRET_KEY", "hosted_models", "HOSTED_MODELS"):
        assert removed not in config, (
            f"docker-compose.test.yml still SETS {removed}, which no longer exists. "
            f"(Mentioning it in a comment is fine and expected.)"
        )
