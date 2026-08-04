"""GPUInfo domain model.

Mirrors `scheduler.models.node.GPUInfo` -- this is the wire contract for the `gpu`
field of a registration payload. The two are separate services with separate
contracts and there is no shared package to hold this, so it is a deliberate
duplicate. **If one changes, the other must.**
"""

from pydantic import BaseModel, Field

CPU_ONLY_GPU_NAME = "cpu-only"


class GPUInfo(BaseModel):
    """GPU hardware as advertised to the Scheduler at registration."""

    name: str = Field(
        ...,
        description="GPU model name, or 'cpu-only' when the host has no usable GPU.",
    )
    vram_total_gb: float = Field(
        ...,
        ge=0,
        description="Total VRAM in gigabytes. 0.0 on a host with no GPU.",
    )
    vram_available_gb: float = Field(
        ...,
        ge=0,
        description="Currently free VRAM in gigabytes.",
    )


def cpu_only_gpu() -> GPUInfo:
    """Return the honest profile for a host with no detectable GPU.

    This is what hardware discovery degrades to on any failure. It advertises
    zero VRAM, which excludes the node from every task carrying a `min_vram_gb`
    requirement -- the correct outcome, and the one the previous hardcoded
    16.0 GB silently defeated.
    """
    return GPUInfo(name=CPU_ONLY_GPU_NAME, vram_total_gb=0.0, vram_available_gb=0.0)
