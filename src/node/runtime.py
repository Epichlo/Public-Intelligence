"""Node runtime lifecycle orchestration."""

import asyncio
import logging
import os
import socket
from asyncio import sleep as async_sleep
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any

from node.clients import OllamaClient, SchedulerClient
from node.core.configuration import Settings
from node.models import Heartbeat, NodeInfo

logger = logging.getLogger(__name__)


class Runtime:
    """Manages the lifecycle, registration, and periodic updates of the Node."""

    def __init__(
        self,
        settings: Settings,
        scheduler_client: SchedulerClient | None = None,
        ollama_client: OllamaClient | None = None,
    ) -> None:
        """Initialize the Runtime.

        Args:
            settings: Loaded configuration settings.
            scheduler_client: Optional pre-configured Scheduler client.
            ollama_client: Optional pre-configured Ollama client.
        """
        self.settings = settings
        self.scheduler_client = scheduler_client or SchedulerClient(settings)
        self.ollama_client = ollama_client or OllamaClient(settings)
        self.heartbeat_task: asyncio.Task[None] | None = None
        self.is_running = False

    async def start(self) -> None:
        """Start the runtime by registering and starting background tasks."""
        if self.is_running:
            return
        self.is_running = True

        try:
            # 1. Discover hosted models
            models = await self.ollama_client.list_models()

            # 2. Build NodeInfo
            node_info = NodeInfo(
                node_id=self.settings.node_id,
                hostname=self.settings.hostname,
                region=self.settings.region,
                ip_address=self._resolve_ip(),
                cpu_cores=self._get_cpu_cores(),
                ram_total_gb=self._get_ram_total_gb(),
                available_models=models,
            )

            # 3. Register with Scheduler
            await self.scheduler_client.register(node_info)

            # 4. Start periodic heartbeats
            self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        except Exception:
            self.is_running = False
            raise

    async def stop(self) -> None:
        """Stop the runtime, unregistering from Scheduler and cancelling tasks."""
        if not self.is_running:
            return
        self.is_running = False

        # Cancel background heartbeat task
        if self.heartbeat_task is not None:
            self.heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.heartbeat_task
            self.heartbeat_task = None

        # Unregister from Scheduler (graceful, ignore errors)
        with suppress(Exception):
            await self.scheduler_client.unregister(self.settings.node_id)

    async def _heartbeat_loop(self) -> None:
        """Periodic background loop that sends heartbeats to the Scheduler."""
        while self.is_running:
            try:
                metrics = self._collect_heartbeat_metrics()
                hb = Heartbeat(
                    node_id=self.settings.node_id,
                    timestamp=datetime.now(timezone.utc),
                    queue_length=metrics["queue_length"],
                    cpu_utilization=metrics["cpu_utilization"],
                    ram_available_gb=metrics["ram_available_gb"],
                    gpu_utilization=metrics["gpu_utilization"],
                    vram_available_gb=metrics["vram_available_gb"],
                )
                await self.scheduler_client.heartbeat(hb)
                logger.info(
                    "Heartbeat sent successfully for node: %s",
                    self.settings.node_id,
                )
            except Exception as e:
                logger.error("Failed to send heartbeat: %s", e)

            try:
                await async_sleep(self.settings.heartbeat_interval_seconds)
            except asyncio.CancelledError:
                break

    def _resolve_ip(self) -> str:
        """Resolve settings hostname to an IP address."""
        if self.settings.hostname == "localhost":
            return "127.0.0.1"
        try:
            return socket.gethostbyname(self.settings.hostname)
        except socket.gaierror:
            return "127.0.0.1"

    def _get_cpu_cores(self) -> int:
        """Determine CPU cores available on the system."""
        return os.cpu_count() or 4

    def _get_ram_total_gb(self) -> float:
        """Retrieve total system RAM (placeholder)."""
        return 16.0

    def _collect_heartbeat_metrics(self) -> dict[str, Any]:
        """Collect current metrics for heartbeat reports (placeholders)."""
        return {
            "queue_length": 0,
            "cpu_utilization": 15.0,
            "ram_available_gb": 8.0,
            "gpu_utilization": 0.0,
            "vram_available_gb": 0.0,
        }
