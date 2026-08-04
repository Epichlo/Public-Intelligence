"""Node representation models for compute nodes in the scheduler."""

from enum import StrEnum

from pydantic import BaseModel, Field


class NodeStatus(StrEnum):
    """Operational status of a compute node."""

    ONLINE = "online"
    OFFLINE = "offline"
    BUSY = "busy"
    UNKNOWN = "unknown"


class GPUInfo(BaseModel):
    """GPU hardware information for a compute node."""

    name: str = Field(description="GPU model name, or 'cpu-only' when there is no GPU")
    # `ge=0`, not `gt=0`: a host with no GPU must be able to say so. This was `gt=0`
    # only because every node hardcoded a 16 GB "unknown" card at registration and so
    # trivially satisfied it. A CPU-only node reporting 0.0 is filtered out of any task
    # carrying `min_vram_gb`, which is the correct outcome; `algorithm.py` already
    # guards its `vram_available / vram_total` ratio against a zero denominator.
    # Mirrored by `node.models.gpu_info.GPUInfo` -- if this changes, that must too.
    vram_total_gb: float = Field(ge=0, description="Total VRAM in gigabytes; 0.0 if no GPU")
    vram_available_gb: float = Field(ge=0, description="Available VRAM in gigabytes")


class Node(BaseModel):
    """Representation of a compute node in the scheduler network.

    Contains identity, hardware capabilities, and loaded models.
    This is a pure data model with no business logic, storage,
    or networking.
    """

    node_id: str = Field(description="Unique identifier for the node")
    hostname: str = Field(description="Node hostname")
    ip_address: str = Field(description="Node IP address")
    region: str = Field(description="Geographic region of the node")
    gpu: GPUInfo = Field(description="GPU hardware information")
    cpu_cores: int = Field(gt=0, description="Number of CPU cores")
    ram_total_gb: float = Field(gt=0, description="Total RAM in gigabytes")
    available_models: list[str] = Field(
        default_factory=list, description="Loaded model identifiers"
    )


class Reachability(StrEnum):
    """How the Scheduler can actually reach a node."""

    MESH = "mesh"
    HTTP = "http"


class NodeView(Node):
    """A node as presented by `GET /nodes`, with how it is reachable.

    `ip_address` on its own is misleading: every installer-provisioned node
    registers `127.0.0.1`, which would be the Scheduler dialling itself. Dispatch
    actually reaches those nodes over the Zenoh mesh. This carries that distinction
    into the API so a reader is not left inferring reachability from an address
    that does not support the inference.

    `reachability` is populated from the registry's own mesh observations by
    `from_node`, never from the registration payload -- it is excluded from `Node`
    for the same reason the per-node token is: a node must not be able to assert it.
    """

    reachability: Reachability = Field(
        description="How dispatch reaches this node: observed on the mesh, or HTTP only"
    )

    @classmethod
    def from_node(cls, node: Node, *, mesh_reachable: bool) -> "NodeView":
        """Build a view of `node`, stamping reachability the registry observed."""
        return cls(
            **node.model_dump(),
            reachability=Reachability.MESH if mesh_reachable else Reachability.HTTP,
        )
