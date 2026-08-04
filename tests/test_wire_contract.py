"""The Node and the Scheduler must agree on what goes over the wire.

`Node.NodeInfo` and `Scheduler.Node` are two independently-defined pydantic models
in two separate git repositories that describe the same registration payload. The
same is true of the two `Heartbeat` models. Nothing checked that they agreed --
the only thing keeping them compatible was whoever last edited one remembering to
edit the other.

That seam was modified twice in two days (roadmap 1.2 added `gpu`, 1.3 changed what
the heartbeat carries) and both times it worked only because it was kept in sync by
hand. The failure mode it protects against is the expensive kind: green unit tests
on both sides, and a 422 the first time a real node registers.

These tests build a payload with the **Node's own serialiser** and feed it to the
**Scheduler's own model**. Reimplementing either side here would only prove this
file agrees with itself.

This is the root suite because it is the only interpreter where both `node` and
`scheduler` import.
"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from node.clients.scheduler import build_heartbeat_payload, build_registration_payload
from node.core.hardware import detect_gpu, detect_host_metrics, detect_ram_total_gb
from node.models import GPUInfo, Heartbeat, ModelInfo, NodeInfo
from scheduler.models.heartbeat import Heartbeat as SchedulerHeartbeat
from scheduler.models.node import Node as SchedulerNode


def _node_info(**overrides: object) -> NodeInfo:
    defaults: dict[str, object] = {
        "node_id": "contract-node",
        "hostname": "node.local",
        "region": "us-east",
        "ip_address": "192.168.1.50",
        "cpu_cores": 8,
        "ram_total_gb": 32.0,
        "gpu": GPUInfo(
            name="NVIDIA GeForce RTX 4090",
            vram_total_gb=24.0,
            vram_available_gb=20.0,
        ),
        "available_models": [
            ModelInfo(name="llama3-8b", size_gb=4.7, family="llama", context_length=8192)
        ],
    }
    defaults.update(overrides)
    return NodeInfo(**defaults)  # type: ignore[arg-type]


def _heartbeat(**overrides: object) -> Heartbeat:
    defaults: dict[str, object] = {
        "node_id": "contract-node",
        "timestamp": datetime.now(UTC),
        "queue_length": 3,
        "cpu_utilization": 41.5,
        "ram_available_gb": 12.25,
        "gpu_utilization": 62.0,
        "vram_available_gb": 9.5,
    }
    defaults.update(overrides)
    return Heartbeat(**defaults)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------


def test_registration_payload_satisfies_the_scheduler_model() -> None:
    """What the Node sends must be what the Scheduler accepts."""
    payload = build_registration_payload(_node_info())

    node = SchedulerNode.model_validate(payload)

    assert node.node_id == "contract-node"
    assert node.gpu.name == "NVIDIA GeForce RTX 4090"
    assert node.gpu.vram_total_gb == 24.0
    assert node.cpu_cores == 8
    assert node.ram_total_gb == 32.0


def test_registration_flattens_models_to_the_names_the_scheduler_expects() -> None:
    """NodeInfo carries ModelInfo objects; Scheduler.Node takes bare names."""
    payload = build_registration_payload(
        _node_info(
            available_models=[
                ModelInfo(name="llama3-8b", size_gb=4.7, family="llama", context_length=8192),
                ModelInfo(name="mistral-7b", size_gb=4.1, family="mistral", context_length=8192),
            ]
        )
    )

    assert payload["available_models"] == ["llama3-8b", "mistral-7b"]
    assert SchedulerNode.model_validate(payload).available_models == ["llama3-8b", "mistral-7b"]


def test_cpu_only_node_registration_crosses_the_boundary() -> None:
    """The honest 0 GB case must survive the round trip, not 422.

    `GPUInfo.vram_total_gb` was `gt=0` on the Scheduler until roadmap 1.2, which
    only ever passed because every node hardcoded 16 GB.
    """
    payload = build_registration_payload(
        _node_info(gpu=GPUInfo(name="cpu-only", vram_total_gb=0.0, vram_available_gb=0.0))
    )

    node = SchedulerNode.model_validate(payload)

    assert node.gpu.vram_total_gb == 0.0
    assert node.gpu.name == "cpu-only"


def test_node_with_no_models_registers() -> None:
    """A node whose Ollama was unreachable advertises nothing and still registers."""
    payload = build_registration_payload(_node_info(available_models=[]))

    assert SchedulerNode.model_validate(payload).available_models == []


@pytest.mark.anyio
async def test_a_payload_built_from_this_machine_is_accepted() -> None:
    """The real detection path, not a fixture, must produce an acceptable payload.

    Catches a whole-pipeline mismatch that hand-built fixtures cannot: if
    `detect_gpu` ever returned a shape the Scheduler rejects -- a negative value, a
    name it will not take -- every unit test would still pass.
    """
    payload = build_registration_payload(
        _node_info(gpu=await detect_gpu(), ram_total_gb=detect_ram_total_gb())
    )

    node = SchedulerNode.model_validate(payload)

    assert node.gpu.vram_total_gb >= 0.0
    assert node.ram_total_gb > 0.0


# --------------------------------------------------------------------------
# Heartbeat
# --------------------------------------------------------------------------


def test_heartbeat_payload_satisfies_the_scheduler_model() -> None:
    """The Scheduler's Heartbeat requires a `status` the Node's model lacks."""
    payload = build_heartbeat_payload(_heartbeat())

    hb = SchedulerHeartbeat.model_validate(payload)

    assert hb.node_id == "contract-node"
    assert hb.queue_length == 3
    assert hb.cpu_utilization == 41.5
    assert hb.vram_available_gb == 9.5
    assert hb.status == "online"


def test_heartbeat_without_injected_status_is_rejected() -> None:
    """Pins *why* build_heartbeat_payload exists.

    If someone simplifies it to a plain `model_dump()`, this fails rather than the
    breakage surfacing as a 422 against a live Scheduler.
    """
    raw = _heartbeat().model_dump(mode="json")

    with pytest.raises(ValidationError, match="status"):
        SchedulerHeartbeat.model_validate(raw)


@pytest.mark.anyio
async def test_measured_metrics_produce_an_acceptable_heartbeat() -> None:
    """Real measured values from this host must cross the boundary.

    Roadmap 1.3 changed every one of these from a constant to a measured figure.
    An out-of-range reading -- a driver reporting >100% utilisation, a negative
    free-VRAM figure -- would be rejected here rather than in production.
    """
    metrics = await detect_host_metrics()
    payload = build_heartbeat_payload(
        _heartbeat(
            cpu_utilization=metrics.cpu_utilization,
            ram_available_gb=metrics.ram_available_gb,
            gpu_utilization=metrics.gpu_utilization,
            vram_available_gb=metrics.vram_available_gb,
        )
    )

    hb = SchedulerHeartbeat.model_validate(payload)

    assert 0.0 <= hb.cpu_utilization <= 100.0
    assert 0.0 <= hb.gpu_utilization <= 100.0
    assert hb.vram_available_gb >= 0.0


# --------------------------------------------------------------------------
# Field-level drift
# --------------------------------------------------------------------------


def test_every_scheduler_required_field_is_supplied_by_the_node() -> None:
    """Adding a required field to Scheduler.Node must fail here, not in production.

    The failure this catches is asymmetric and quiet: the Scheduler's tests pass
    (they build the model directly), the Node's tests pass (they never see the
    Scheduler's model), and only a real registration 422s.
    """
    supplied = set(build_registration_payload(_node_info()))
    required = {
        name for name, f in SchedulerNode.model_fields.items() if f.is_required()
    }

    assert required <= supplied, (
        f"Scheduler.Node requires {sorted(required - supplied)}, which the Node never sends. "
        "Add it to NodeInfo/build_registration_payload, or give it a default."
    )


def test_every_scheduler_required_heartbeat_field_is_supplied() -> None:
    """Same guard for the heartbeat contract."""
    supplied = set(build_heartbeat_payload(_heartbeat()))
    required = {
        name for name, f in SchedulerHeartbeat.model_fields.items() if f.is_required()
    }

    assert required <= supplied, (
        f"Scheduler.Heartbeat requires {sorted(required - supplied)}, which the Node never sends."
    )
