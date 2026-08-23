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

The RUNTIME claim is covered elsewhere now: `.github/workflows/ci.yml::compose-e2e`
brings the stack up on a Docker-capable runner, waits for both workers to register,
refuses an uncredentialed request, and drives one credentialed completion through
gateway -> scheduler -> mesh -> node. Before that job existed, two containers had
never exchanged an inference request anywhere (`docs/PREMISES.md` P2). What this file
still owns is everything that can be judged without a daemon: every variable bound,
the gateway credential present and operator-provided, healthchecks probing with tools
the image actually contains and endpoints something in this stack actually serves,
every container declaring a start command, and image builds whose context can
resolve the local-path `public-intelligence-shared`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from env_binding import accepted_env_names
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
    accepted = accepted_env_names(settings_cls)

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

    Asserted against the LIVE scheduler environment block, not the raw text: the
    first version of this check grepped for "JWT_PUBLIC_KEY" anywhere in the file,
    which a COMMENT mentioning the key satisfies. A check that passes on its own
    documentation is the W9 pattern. The variable must also be an operator-provided
    substitution, not a hardcoded literal: C4's whole point is that no key of
    unknown provenance exists.
    """
    import importlib

    settings_cls: type[BaseSettings] = importlib.import_module("scheduler.core.config").Settings
    accepted = accepted_env_names(settings_cls)

    env = _service_env_block("scheduler")
    assert "SCHEDULER_JWT_PUBLIC_KEY" in env, (
        "docker-compose.test.yml sets no JWT public key on the scheduler service, "
        "so /v1/chat/completions refuses everyone (ROADMAP C4) and the two-node "
        "demo cannot serve a request."
    )
    assert "SCHEDULER_JWT_PUBLIC_KEY" in accepted, (
        "the compose file sets a JWT public key under a name scheduler Settings "
        "does not read -- silently ignored, exactly the NODE_ID class of defect."
    )
    value = env["SCHEDULER_JWT_PUBLIC_KEY"]
    assert value.startswith("${"), (
        f"SCHEDULER_JWT_PUBLIC_KEY is hardcoded in docker-compose.test.yml "
        f"({value!r}). C4 forbids keys of unknown provenance: the public half must "
        f"come from the operator's environment (scripts/mint_token.py mints it)."
    )


def _service_env_block(service: str) -> dict[str, str]:
    """Name -> raw value for ONE service's `environment:` list entries."""
    values: dict[str, str] = {}
    current: str | None = None
    in_env = False
    for raw in COMPOSE.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if re.match(r"^  [a-z0-9_-]+:$", line):
            current = line.strip().rstrip(":")
            in_env = False
        elif re.match(r"^    environment:$", line) and current == service:
            in_env = True
        elif in_env and re.match(r"^      - [A-Z]", line):
            name, _, value = line.strip().lstrip("- ").partition("=")
            values[name] = value
        elif in_env and line and not line.startswith("      "):
            in_env = False
    return values


def test_the_scheduler_healthcheck_needs_nothing_the_image_lacks() -> None:
    """A healthcheck that calls a binary the image does not contain never passes.

    The probe used `curl`, which python:3.12-slim does not ship -- so the Scheduler
    could never report healthy and `depends_on: condition: service_healthy` would
    have kept both nodes waiting forever, on a stack nobody had ever run. Found by
    reading; pinned so it stays found.
    """
    text = COMPOSE.read_text(encoding="utf-8")

    # The stdlib probe the runtime image is guaranteed to serve: it has python.
    assert "urllib.request.urlopen('http://localhost:8000/health')" in text, (
        "the scheduler healthcheck no longer probes /health with python's stdlib; "
        "whatever replaced it must exist inside the runtime image."
    )

    probing = [
        line.strip()
        for line in text.splitlines()
        if re.match(r"^\s*test:", line) and re.search(r"\b(curl|wget)\b", line)
    ]
    assert not probing, f"a healthcheck shells out to a tool slim images do not contain: {probing}"


def test_every_service_image_builds_from_a_context_that_has_shared() -> None:
    """`public-intelligence-shared` has no index presence (ROADMAP C8).

    Both package Dockerfiles pip-installed from their own directory as build
    context while hard-depending on that name, so NEITHER image could ever have
    built -- "No matching distribution found", before a single container started.
    The fix lives here rather than in packages/: the build context is the repo root
    and shared is copied in and installed FIRST, the order install.sh and CI
    already knew. Pinned so a later edit cannot quietly shrink the context back to
    something that cannot see packages/shared.
    """
    text = COMPOSE.read_text(encoding="utf-8")

    builds = re.findall(r"context:\s*(\S+)", text)
    assert builds, "docker-compose.test.yml defines no builds"
    for context in builds:
        assert context == ".", (
            f"a service builds from context {context!r}; only the repo root can see "
            f"packages/shared, which every image must install to resolve "
            f"public-intelligence-shared"
        )

    assert re.search(r"COPY packages/shared ", text), (
        "no build copies packages/shared into its context staging, so pip resolves "
        "public-intelligence-shared from the index and fails"
    )


def _service_blocks() -> dict[str, str]:
    """Every service's raw YAML block, keyed by name -- no YAML dependency.

    Scoped to the `services:` section: `networks:` also holds two-space-indented
    keys, and the top-level `x-service-build` anchor is not a service either.
    """
    blocks: dict[str, list[str]] = {}
    current: str | None = None
    in_services = False
    for raw in COMPOSE.read_text(encoding="utf-8").splitlines():
        if re.match(r"^services:$", raw):
            in_services = True
            continue
        if in_services and raw and not raw[0].isspace():
            in_services = False  # the next top-level key ends the section
        if not in_services:
            continue
        found = re.match(r"^  ([a-z0-9_-]+):\s*$", raw)
        if found:
            current = found.group(1)
            blocks[current] = []
        elif current:
            blocks[current].append(raw)
    return {name: "\n".join(body) for name, body in blocks.items()}


def test_every_compose_service_declares_a_start_command() -> None:
    """A container with no start command serves nothing, ever.

    The shared build template once ended at WORKDIR with no CMD, so both service
    containers inherited the base image's default -- an interactive python3 on
    stdin -- and exited the instant they started. Nothing crashed: the healthcheck
    just never passed, `depends_on: condition: service_healthy` never resolved, and
    the E2E job would have timed out on every run. Found by audit AFTER the stack
    was committed as runnable, which is exactly when a static pin earns its keep.
    """
    blocks = _service_blocks()
    expected = {"scheduler", "node-worker-1", "node-worker-2", "ollama-spoof"}
    missing = expected - set(blocks)
    assert not missing, f"docker-compose.test.yml lost services: {sorted(missing)}"

    commandless = []
    for name in sorted(expected):
        block = blocks[name]
        # Either compose-level `command:` or a CMD baked into that service's own
        # inline Dockerfile (the stand-in bakes its CMD; the three services declare).
        has_compose_command = re.search(r"^    command:", block, flags=re.MULTILINE)
        has_dockerfile_cmd = re.search(r"^\s+CMD\b", block, flags=re.MULTILINE)
        if not (has_compose_command or has_dockerfile_cmd):
            commandless.append(name)

    assert not commandless, (
        f"{commandless} declare no start command, so they inherit the base image "
        f"default (interactive python3 on stdin), exit at once, and nothing "
        f"downstream can ever go healthy."
    )


def test_each_service_serves_what_its_healthcheck_probes() -> None:
    """The probe must point at something this stack actually runs.

    The scheduler's healthcheck polls /health on :8000, so its start command must be
    the uvicorn serving scheduler.main on :8000 -- not merely SOME long-running
    process, which would go healthy while serving nothing. The workers have no
    healthcheck; their registration IS their liveness proof, so what is pinned here
    is only that they still run the node entrypoint rather than anything else that
    merely stays up.
    """
    blocks = _service_blocks()

    scheduler_command = re.search(r"^    command:\s*(.+)$", blocks["scheduler"], flags=re.MULTILINE)
    assert scheduler_command, "scheduler declares no start command"
    joined = " ".join(re.findall(r'"([^"]+)"', scheduler_command.group(1)))
    assert "uvicorn" in joined and "scheduler.main:app" in joined, (
        f"the scheduler does not start its FastAPI app: {joined!r}"
    )
    assert "--port" in joined and "8000" in joined, (
        f"the scheduler does not serve :8000, which is the port its healthcheck probes: {joined!r}"
    )

    for worker in ("node-worker-1", "node-worker-2"):
        worker_command = re.search(r"^    command:\s*(.+)$", blocks[worker], flags=re.MULTILINE)
        assert worker_command, f"{worker} declares no start command"
        worker_joined = " ".join(re.findall(r'"([^"]+)"', worker_command.group(1)))
        assert worker_joined.strip() == "python -m node.main", (
            f"{worker} does not run the node entrypoint: {worker_joined!r}"
        )


def test_the_two_workers_do_not_share_a_credential() -> None:
    """Decision D9, checked in the only file that runs two nodes at once.

    Both workers carried `NODE_NETWORK_AUTH_TOKEN=local-dev-token` -- the same value
    as each other and as the Scheduler's fleet token. ROADMAP 2.7 keys every
    state-changing mesh message on the node's own credential so that one host cannot
    forge messages as another; with one shared value that property is not merely
    untested here, it is false, and this is the file a person runs to see two nodes
    work.

    The admission token is expected to be shared -- that is what a fleet secret is.
    The per-node one is not.
    """
    values: dict[str, dict[str, str]] = {}
    current: str | None = None
    in_env = False
    for raw in COMPOSE.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if re.match(r"^  [a-z0-9_-]+:$", line):
            current = line.strip().rstrip(":")
            values.setdefault(current, {})
            in_env = False
        elif re.match(r"^    environment:$", line):
            in_env = True
        elif in_env and re.match(r"^      - [A-Z]", line) and current:
            name, _, value = line.strip().lstrip("- ").partition("=")
            values[current][name] = value
        elif in_env and line and not line.startswith("      "):
            in_env = False

    workers = {name: env for name, env in values.items() if name.startswith("node-worker")}
    assert len(workers) >= 2, "expected docker-compose.test.yml to define two workers"

    credentials = {name: env.get("NODE_NETWORK_AUTH_TOKEN") for name, env in workers.items()}
    assert all(credentials.values()), (
        f"a worker has no NODE_NETWORK_AUTH_TOKEN, so its control API serves "
        f"nothing and the Scheduler cannot dispatch to it: {credentials}"
    )
    assert len(set(credentials.values())) == len(credentials), (
        f"two workers share one NODE_NETWORK_AUTH_TOKEN, so either can seal mesh "
        f"envelopes as the other and ROADMAP 2.7's per-node isolation is false in "
        f"the demo itself (decision D9): {credentials}"
    )

    fleet = values.get("scheduler", {}).get("SCHEDULER_NETWORK_AUTH_TOKEN")
    for name, credential in credentials.items():
        assert credential != fleet, (
            f"{name}'s own credential IS the fleet's admission secret, which every "
            f"host on the fleet holds -- the exact conflation D9 separates"
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
