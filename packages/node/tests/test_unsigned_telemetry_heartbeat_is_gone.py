"""The unsigned telemetry look-alike is gone, and stays gone.

`node.telemetry.heartbeat.ZenohTelemetryHeartbeat` published plaintext JSON
on `public-intelligence/net/nodes/*/telemetry`. Since authenticated mesh
ingress (ROADMAP 2.7), the Scheduler opens every telemetry frame with the
node's sealed envelope and silently drops whatever fails to open -- so this
class's output never reached a registry anywhere, and its failure mode was
silence: no error, no log on the receiving side, just nodes whose metrics
never arrived. Production telemetry goes through
`node.core.telemetry.TelemetryEmitter`, which seals envelopes.

Deleted rather than fixed: an unsigned publisher of the same topic is a trap
waiting for the next person who finds it first and wires it up. This file is
the ratchet.
"""

import importlib

import pytest

import node.telemetry


def test_the_unsigned_heartbeat_stays_unimportable() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("node.telemetry.heartbeat")


def test_it_is_not_re_exported_from_the_package() -> None:
    assert not hasattr(node.telemetry, "ZenohTelemetryHeartbeat")
    assert "ZenohTelemetryHeartbeat" not in node.telemetry.__all__


def test_the_real_telemetry_paths_survived() -> None:
    """Guards the guard: the ratchet must not celebrate deleting the wrong thing.

    The live emitter (sealed envelopes) and the collector the control API reads
    must both still be importable.
    """
    from node.core.telemetry import TelemetryEmitter  # noqa: F401
    from node.telemetry import TelemetryCollector  # noqa: F401
