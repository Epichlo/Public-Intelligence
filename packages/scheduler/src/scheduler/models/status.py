"""Operational status response models."""

from datetime import datetime

from pydantic import BaseModel, Field

from scheduler.models.node import NodeStatus


class NodeStatusSnapshot(BaseModel):
    """Static and latest runtime state for a registered node."""

    node_id: str
    hostname: str
    region: str
    status: NodeStatus
    heartbeat_at: datetime | None = None
    queue_length: int | None = None
    cpu_utilization: float | None = None
    gpu_utilization: float | None = None
    vram_available_gb: float | None = None


class NetworkStatus(BaseModel):
    """Scheduler transport status exposed to operators."""

    connected: bool = Field(description="Whether the Scheduler has an active Zenoh session")
    mode: str = Field(description="Configured Scheduler transport mode")


class SchedulerStatusResponse(BaseModel):
    """Aggregated Scheduler status for the control-plane vertical slice."""

    status: str
    version: str
    environment: str
    uptime_seconds: float
    timestamp: datetime
    network: NetworkStatus
    nodes: list[NodeStatusSnapshot]
