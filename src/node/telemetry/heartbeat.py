"""Zenoh telemetry heartbeat loop publisher and process exit deadman switch."""

import asyncio
import contextlib
import json
import logging
import signal

import zenoh

from node.core.configuration import Settings
from node.telemetry.collector import TelemetryCollector

logger = logging.getLogger(__name__)


class ZenohTelemetryHeartbeat:
    """Publishes system hardware utilization stats periodically over Zenoh."""

    def __init__(
        self, settings: Settings, collector: TelemetryCollector | None = None
    ) -> None:
        """Initialize the ZenohTelemetryHeartbeat.

        Args:
            settings: Node configuration settings.
            collector: Hardware telemetry collector instance.
        """
        self.settings = settings
        self.collector = collector or TelemetryCollector()
        self.session: zenoh.Session | None = None
        self.publisher: zenoh.Publisher | None = None
        self._key_expr = (
            f"public-intelligence/net/nodes/{self.settings.node_id}/telemetry"
        )
        self._loop_task: asyncio.Task[None] | None = None
        self.is_running = False

    async def start(self) -> None:
        """Open the Zenoh session, register signal handlers, and start task loop."""
        if self.is_running:
            return
        self.is_running = True

        logger.info("Opening Zenoh telemetry session...")
        try:
            self.session = zenoh.open(zenoh.Config())
            self.publisher = self.session.declare_publisher(self._key_expr)
            self._loop_task = asyncio.create_task(self._broadcast_loop())
            self.register_signal_handlers()
            logger.info(
                "Zenoh telemetry heartbeat broadcast loop started: %s",
                self._key_expr,
            )
        except Exception as e:
            logger.error("Failed to start Zenoh telemetry: %s", e)
            await self.stop()
            raise

    async def stop(self) -> None:
        """Gracefully stop background loop, execute deadman switch, close session."""
        if not self.is_running:
            return
        self.is_running = False

        # 1. Stop background loop task
        if self._loop_task is not None:
            self._loop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._loop_task
            self._loop_task = None

        # 2. Publish graceful exit deadman switch frame
        await self._publish_offline_frame()

        # 3. Cleanup Zenoh objects
        try:
            if self.publisher is not None:
                self.publisher.undeclare()  # type: ignore[no-untyped-call]
                self.publisher = None
            if self.session is not None:
                self.session.close()  # type: ignore[no-untyped-call]
                self.session = None
        except Exception as e:
            logger.error("Error closing Zenoh telemetry: %s", e)
        finally:
            self.session = None
            logger.info("Zenoh telemetry broadcast loop terminated.")

    def register_signal_handlers(self) -> None:
        """Register SIGINT/SIGTERM handlers.

        Triggers stop() on process interruption.
        """
        from collections.abc import Callable

        try:
            loop = asyncio.get_running_loop()

            def make_handler(s: int) -> Callable[[], asyncio.Task[None]]:
                return lambda: asyncio.create_task(self._handle_signal(s))

            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, make_handler(sig))
        except (NotImplementedError, RuntimeError):
            # Safe fallback for non-supported loop types (e.g. Windows)
            pass

    async def _handle_signal(self, sig: int) -> None:
        """Async callback triggered upon system signals."""
        logger.info(
            "Captured termination signal %s. Executing graceful deadman switch...",
            sig,
        )
        await self.stop()

    async def _publish_offline_frame(self) -> None:
        """Transmit a structured exit status payload indicating OFFLINE state."""
        if self.publisher is None:
            return
        try:
            offline_payload = {
                "node_id": self.settings.node_id,
                "status": "OFFLINE",
                "cpu_utilization": 0.0,
                "ram_utilization_pct": 0.0,
                "gpu_utilization": 0.0,
            }
            payload_str = json.dumps(offline_payload)
            logger.info(
                "Broadcasting OFFLINE graceful deadman switch state: %s",
                payload_str,
            )
            self.publisher.put(payload_str)
        except Exception as e:
            logger.error("Failed to publish graceful exit frame: %s", e)

    async def _broadcast_loop(self) -> None:
        """Broadcast resource telemetry metrics every 5.0 seconds."""
        while self.is_running:
            try:
                metrics = await self.collector.collect()
                metrics["node_id"] = self.settings.node_id
                metrics["status"] = "ONLINE"

                payload_str = json.dumps(metrics)
                logger.debug("Publishing telemetry resource report: %s", payload_str)
                if self.publisher is not None:
                    self.publisher.put(payload_str)
            except Exception as e:
                logger.error("Error in telemetry broadcast loop: %s", e)

            try:
                await asyncio.sleep(5.0)
            except asyncio.CancelledError:
                break
