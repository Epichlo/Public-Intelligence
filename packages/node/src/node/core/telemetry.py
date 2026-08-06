"""Telemetry metrics emitter module for Node with AES-256-GCM encryption."""

import asyncio
import logging
import subprocess
import sys
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

import psutil

from node.core.mesh_auth import PURPOSE_TELEMETRY, seal

logger = logging.getLogger(__name__)


def get_cpu_utilization() -> float:
    """Retrieve system CPU utilization percentage.

    Uses psutil, matching `node.core.hardware`, so telemetry and heartbeats cannot
    disagree about the same machine.

    This previously called `os.getloadavg()`, which does not exist on Windows -- the
    AttributeError was caught by a bare `except Exception` whose fallback returned
    `10.0 + random.random() * 20.0`. Every Windows host therefore published a
    **randomly generated** CPU figure into the telemetry mesh, indistinguishable
    from a real reading. mypy found this the first time it was run against the
    Windows platform; the `except` branch had hidden it from every test.

    Load average was also the wrong measure: it is a run-queue depth, not a
    percentage, so dividing by core count only approximated utilisation even on
    POSIX.

    Returns:
        CPU utilization percentage, 0.0-100.0.
    """
    try:
        return round(float(psutil.cpu_percent(interval=None)), 2)
    except Exception as e:
        # Report zero rather than invent a number. A node that cannot read its own
        # CPU should look idle, not plausible.
        logger.warning("CPU utilisation read failed, reporting 0.0: %s", e)
        return 0.0


def get_ram_usage_bytes() -> int:
    """Retrieve system RAM usage in bytes.

    Returns:
        RAM usage in bytes.
    """
    if sys.platform == "darwin":
        try:
            total_bytes = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"]).strip())
            vm_output = subprocess.getoutput("vm_stat")
            pages_free = 0
            pages_speculative = 0
            page_size = 4096
            for line in vm_output.splitlines():
                if "page size of" in line:
                    page_size = int(line.split()[4])
                elif "Pages free:" in line:
                    pages_free = int(line.split()[2].rstrip("."))
                elif "Pages speculative:" in line:
                    pages_speculative = int(line.split()[2].rstrip("."))
            free_bytes = (pages_free + pages_speculative) * page_size
            return max(0, total_bytes - free_bytes)
        except Exception as e:
            logger.debug("Failed to retrieve macOS memory info: %s", e)
            return 8 * 1024 * 1024 * 1024
    elif sys.platform == "linux":
        try:
            with open("/proc/meminfo") as f:
                lines = f.readlines()
            mem_total = 0
            mem_free = 0
            mem_cached = 0
            mem_buffers = 0
            for line in lines:
                parts = line.split()
                if len(parts) >= 2:
                    key = parts[0].rstrip(":")
                    val = int(parts[1]) * 1024
                    if key == "MemTotal":
                        mem_total = val
                    elif key == "MemFree":
                        mem_free = val
                    elif key == "Cached":
                        mem_cached = val
                    elif key == "Buffers":
                        mem_buffers = val
            used = mem_total - mem_free - mem_buffers - mem_cached
            return max(0, used)
        except Exception as e:
            logger.debug("Failed to retrieve Linux memory info: %s", e)
            return 8 * 1024 * 1024 * 1024
    return 8 * 1024 * 1024 * 1024


class TelemetryEmitter:
    """Background emitter publishing encrypted node utilization metrics to Zenoh.

    Runs every 5 seconds.
    """

    def __init__(
        self, node_id: str, zenoh_session: Any, auth_token: str | None, interval: float = 5.0
    ) -> None:
        """Initialize the TelemetryEmitter.

        Args:
            node_id: Unique identifier for this node.
            zenoh_session: Active Zenoh session.
            auth_token: This node's own NODE_NETWORK_AUTH_TOKEN, from which the
                telemetry signing key is derived. Without one the emitter runs but
                publishes nothing -- the Scheduler could not verify it anyway, and
                emitting unsigned frames would only look like it worked.
            interval: Loop iteration duration in seconds.
        """
        self.node_id = node_id
        self.auth_token = auth_token
        self.zenoh_session = zenoh_session
        self.interval = interval
        self.task: asyncio.Task[None] | None = None
        self.is_running = False
        self.topic = f"public-intelligence/net/nodes/{self.node_id}/telemetry"

    def start(self) -> None:
        """Start the background metrics emission task."""
        if self.is_running:
            return
        self.is_running = True
        self.task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        """Stop the background metrics emission task."""
        if not self.is_running:
            return
        self.is_running = False
        if self.task is not None:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
            self.task = None

    async def _loop(self) -> None:
        """Background loop executing every interval.

        Signed with a key derived from this node's own credential. It used to be a
        fleet-wide `TELEMETRY_SECRET_KEY` defaulting to a constant published in this
        repository, so anyone could forge telemetry for any node and steer
        matchmaking. See specs/authenticated-mesh-ingress.md.
        """
        if not self.auth_token:
            logger.error(
                "No NODE_NETWORK_AUTH_TOKEN configured; telemetry cannot be signed and "
                "will not be published. The Scheduler drops unsigned frames."
            )
            return

        while self.is_running:
            try:
                metrics = {
                    "node_id": self.node_id,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "cpu_utilization": get_cpu_utilization(),
                    "ram_usage_bytes": get_ram_usage_bytes(),
                    "gpu_utilization": 0.0,
                    "vram_usage_bytes": 0,
                }
                payload = seal(
                    metrics,
                    node_id=self.node_id,
                    token=self.auth_token,
                    purpose=PURPOSE_TELEMETRY,
                )

                if self.zenoh_session is not None:
                    self.zenoh_session.put(self.topic, payload)
                    logger.debug("Emitted encrypted telemetry to topic %s", self.topic)
            except Exception as e:
                logger.error("Failed to emit encrypted telemetry: %s", e)

            try:
                await asyncio.sleep(self.interval)
            except asyncio.CancelledError:
                break
