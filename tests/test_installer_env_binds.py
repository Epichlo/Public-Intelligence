"""Every variable the installers write must be one the Node actually reads.

`tests/test_compose_env_matches_settings.py` closed this class of defect for
`docker-compose.test.yml` and stopped there. Its own docstring names the bug --
"`NODE_ID` -- the Node's Settings read `NODE_NODE_ID`" -- and the compose file was
corrected, with a comment explaining the trap.

**Both installers were left writing the broken name.** So the file nobody runs was
fixed and the two files every real host runs were not, and for the entire time since,
every node installed by either script has been called `node-local`.

With one node that is invisible. With two it is a collision: the registry keys on
`node_id`, and so does the mesh queryable `public-intelligence/net/{node_id}/infer`
-- two hosts would answer the same key and occupy the same registry slot. A network
of one works; a network is the point.

The mechanism is worth stating because it is silent by construction: pydantic-settings
does not warn about an env var that matches no field. It cannot -- an unknown name is
indistinguishable from an unrelated one. So a typo'd setting is not an error, it is a
default, and the only way to catch it is to compare the two lists.

See specs/what-two-machines-found.md.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest
from env_binding import accepted_env_names
from pydantic_settings import BaseSettings

REPO_ROOT = Path(__file__).resolve().parent.parent
POSIX = REPO_ROOT / "install.sh"
WINDOWS = REPO_ROOT / "install.ps1"

# Names written into .env for something other than the Node's Settings model.
NOT_NODE_SETTINGS = {
    # These three go into packages/website/.env.local, not packages/node/.env, and
    # are read by Next.js (ROADMAP 3.5). Listing them is a decision someone has to
    # write down, same as LINT_EXEMPT_DIRS -- an unexplained entry here is how a
    # genuinely broken variable gets waved through.
    "NODE_AUTH_TOKEN",
    "NODE_URL",
    "NEXT_PUBLIC_SCHEDULER_URL",
    "SCHEDULER_URL",
}


def _written_names(text: str) -> set[str]:
    """`NODE_*` names that appear as an assignment anywhere in an installer.

    Deliberately catches BOTH the lines written into .env and the lines the dry-run
    prints. ROADMAP C1's defect was a dry-run describing values the real run did not
    write, so a name that appears in only one of the two is itself a finding -- and
    the cheapest way to cover both is not to distinguish them.

    Shell and PowerShell locals are skipped. `local NODE_ID_VAL=...` is a variable
    inside install.sh, not a line in anyone's .env, and flagging it would be a false
    positive -- which is the failure mode that gets a checker switched off.
    """
    names: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if re.match(r"^(local|export|declare|readonly)\s", line):
            continue
        names.update(m.group(1).upper() for m in re.finditer(r"\b(NODE_[A-Z0-9_]+)=", line))
    return names


@pytest.mark.parametrize(
    ("label", "path"),
    [("install.sh", POSIX), ("install.ps1", WINDOWS)],
)
def test_every_installer_env_var_is_read_by_the_node(label: str, path: Path) -> None:
    settings_cls: type[BaseSettings] = importlib.import_module("node.core.configuration").Settings
    accepted = accepted_env_names(settings_cls)

    written = _written_names(path.read_text(encoding="utf-8"))
    unread = sorted(n for n in written if n not in accepted and n not in NOT_NODE_SETTINGS)

    assert not unread, (
        f"{label} writes {unread}, which the Node's Settings never read. "
        f"pydantic-settings ignores an unmatched name silently, so the node keeps "
        f"its default and nothing reports it. This is how every installed node was "
        f"called 'node-local' -- and two of them collide on the registry key and on "
        f"the mesh queryable."
    )


def test_both_installers_can_set_the_node_id() -> None:
    """The specific instance, pinned separately from the general rule.

    The general check above would also pass if an installer simply stopped writing
    an id at all. That is not the fix: a fleet of nodes all defaulting to the same
    identity is the failure, so the installers must actively set one.
    """
    settings_cls: type[BaseSettings] = importlib.import_module("node.core.configuration").Settings
    accepted = accepted_env_names(settings_cls)

    for label, path in (("install.sh", POSIX), ("install.ps1", WINDOWS)):
        written = _written_names(path.read_text(encoding="utf-8"))
        id_names = {n for n in written if n in {"NODE_ID", "NODE_NODE_ID"}}
        assert id_names, f"{label} no longer sets a node id at all"
        assert id_names & accepted, (
            f"{label} sets {sorted(id_names)}, none of which the Node reads: "
            f"every node it installs would be '{settings_cls.model_fields['node_id'].default}'"
        )


def test_the_documented_env_var_name_is_the_one_that_works() -> None:
    """`NODE_ID` is the name every operator will reach for, so it must bind.

    The alternative fix -- rewriting both installers to emit `NODE_NODE_ID` -- leaves
    every already-installed node broken until its owner hand-edits a file, and leaves
    the obvious name a silent no-op forever. Accepting both is what makes existing
    installs start working without anyone touching them.
    """
    settings_cls: type[BaseSettings] = importlib.import_module("node.core.configuration").Settings
    accepted = accepted_env_names(settings_cls)

    assert "NODE_ID" in accepted, (
        "NODE_ID does not bind. It is the name both installers write and the one any "
        "operator would guess, so leaving it unread makes the setting look applied "
        "while doing nothing."
    )
    assert "NODE_NODE_ID" in accepted, (
        "NODE_NODE_ID no longer binds; docker-compose.test.yml relies on it"
    )


def test_two_nodes_configured_differently_get_different_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The property that actually matters, exercised rather than inferred.

    Reading the files proves the installers write a name; this proves the Node
    honours it. Without it, both checks above could pass against a field that
    accepts the variable and ignores its value.
    """
    # Imported concretely rather than through importlib: this test reads `node_id`
    # off the instance, and a `type[BaseSettings]` annotation hides that attribute
    # from the type checker.
    from node.core.configuration import Settings

    monkeypatch.setenv("NODE_ID", "node-worker-1")
    first = Settings(_env_file=None)  # type: ignore[call-arg]

    monkeypatch.setenv("NODE_ID", "node-worker-2")
    second = Settings(_env_file=None)  # type: ignore[call-arg]

    assert first.node_id == "node-worker-1"
    assert second.node_id == "node-worker-2"
    assert first.node_id != second.node_id, (
        "two nodes configured with different ids resolved to the same one, so they "
        "would collide on the registry key and on the mesh queryable"
    )
