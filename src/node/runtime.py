"""Node runtime lifecycle orchestration."""

import asyncio
import logging
import os
import socket
from asyncio import sleep as async_sleep
from contextlib import suppress
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from node.clients import OllamaClient, SchedulerClient, ZenohHeartbeatClient
from node.core.configuration import Settings
from node.core.telemetry import TelemetryEmitter
from node.models import Heartbeat, NodeInfo

logger = logging.getLogger(__name__)


class Runtime:
    """Manages the lifecycle, registration, and periodic updates of the Node."""

    def __init__(
        self,
        settings: Settings,
        scheduler_client: SchedulerClient | None = None,
        ollama_client: OllamaClient | None = None,
        zenoh_client: ZenohHeartbeatClient | None = None,
    ) -> None:
        """Initialize the Runtime.

        Args:
            settings: Loaded configuration settings.
            scheduler_client: Optional pre-configured Scheduler client.
            ollama_client: Optional pre-configured Ollama client.
            zenoh_client: Optional pre-configured Zenoh heartbeat client.
        """
        self.settings = settings
        self.scheduler_client = scheduler_client or SchedulerClient(settings)
        self.ollama_client = ollama_client or OllamaClient(settings)
        self.zenoh_client = zenoh_client or ZenohHeartbeatClient(settings)
        self.heartbeat_task: asyncio.Task[None] | None = None
        self.telemetry_emitter: TelemetryEmitter | None = None
        self.split_stage_sub: Any | None = None
        self.is_running = False

        if TYPE_CHECKING:
            from shared.storage.local import LocalDiskArtifactStore
        else:
            try:
                from shared.storage.local import LocalDiskArtifactStore
            except ModuleNotFoundError:
                from src.shared.storage.local import LocalDiskArtifactStore

        from node.backends.base import InferenceBackend

        self.inference_backend: InferenceBackend | None = None
        self.artifact_store = LocalDiskArtifactStore()
        self.task_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.worker_task: asyncio.Task[None] | None = None
        self.registration_status = "not_started"
        self.last_heartbeat_at: datetime | None = None
        self.last_heartbeat_ok = False
        self.last_heartbeat_error: str | None = None

    async def start(self) -> None:
        """Start the runtime by registering and starting background tasks."""
        if self.is_running:
            return
        self.is_running = True
        self.registration_status = "starting"

        try:
            # 1. Discover hosted models
            try:
                models = await self.ollama_client.list_models()
            except Exception as e:
                logger.warning("ollama_discovery_warning", error=str(e))
                models = []

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
            self.registration_status = "registered"

            # 3.5. Start Zenoh heartbeat client
            self.zenoh_client.start()

            # 3.6. Start telemetry emitter
            if self.zenoh_client.session is not None:
                self.telemetry_emitter = TelemetryEmitter(
                    self.settings.node_id, self.zenoh_client.session
                )
                self.telemetry_emitter.start()
                self._setup_split_stage_listener()

            # 4. Start periodic heartbeats
            self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())

            # 5. Start task consumer worker loop
            self.worker_task = asyncio.create_task(self._worker_loop())
        except Exception:
            self.is_running = False
            self.registration_status = "failed"
            raise

    async def stop(self) -> None:
        """Stop the runtime, unregistering from Scheduler and cancelling tasks."""
        if not self.is_running:
            return
        self.is_running = False
        self.registration_status = "stopping"

        # Undeclare split stage subscriber
        if self.split_stage_sub is not None:
            with suppress(Exception):
                if hasattr(self.split_stage_sub, "undeclare"):
                    self.split_stage_sub.undeclare()
            self.split_stage_sub = None

        # Cancel background heartbeat task
        if self.heartbeat_task is not None:
            self.heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.heartbeat_task
            self.heartbeat_task = None

        # Cancel task consumer worker task
        if self.worker_task is not None:
            self.worker_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.worker_task
            self.worker_task = None

        # Stop telemetry emitter
        if self.telemetry_emitter is not None:
            with suppress(Exception):
                await self.telemetry_emitter.stop()
            self.telemetry_emitter = None

        # Stop Zenoh heartbeat client
        with suppress(Exception):
            self.zenoh_client.stop()

        # Unregister from Scheduler (graceful, ignore errors)
        with suppress(Exception):
            await self.scheduler_client.unregister(self.settings.node_id)
        self.registration_status = "unregistered"

    async def _worker_loop(self) -> None:
        """Background task consumer that processes tasks using the inference backend."""
        import json

        while self.is_running:
            try:
                task = await self.task_queue.get()
                task_id = task["task_id"]
                model_name = task.get("model_name") or task.get("model", "echo")
                prompt = task["prompt"]
                options = task.get("options")

                # Setup default EchoBackend if none configured
                if self.inference_backend is None:
                    from node.backends.mock import EchoBackend

                    self.inference_backend = EchoBackend()

                # 1. Execute run pass using InferenceBackend client
                output = await self.inference_backend.generate(
                    model=model_name, prompt=prompt, options=options
                )

                # 2. Save generated response to ArtifactStore
                metadata = await self.artifact_store.save_artifact(
                    task_id=task_id,
                    data=output.encode("utf-8"),
                    metadata={
                        "model": model_name,
                        "prompt_length": len(prompt),
                    },
                )

                # 3. Report only the resulting ArtifactMetadata block via Zenoh
                if self.zenoh_client.session is not None:
                    path = f"public-intelligence/net/tasks/{task_id}/result"
                    self.zenoh_client.session.put(path, json.dumps(metadata.model_dump()))

                self.task_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    "Error executing task in worker processor loop: %s",
                    e,
                    exc_info=True,
                )
                await async_sleep(0.1)

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
                self.last_heartbeat_at = hb.timestamp
                self.last_heartbeat_ok = True
                self.last_heartbeat_error = None
                logger.info(
                    "Heartbeat sent successfully for node: %s",
                    self.settings.node_id,
                )

                try:
                    self.zenoh_client.publish(hb)
                    logger.info(
                        "Heartbeat published via Zenoh successfully for node: %s",
                        self.settings.node_id,
                    )
                except Exception as ze:
                    logger.error("Failed to publish heartbeat via Zenoh: %s", ze)
            except Exception as e:
                self.last_heartbeat_ok = False
                self.last_heartbeat_error = str(e)
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

    def _setup_split_stage_listener(self) -> None:
        """Subscribe to split-stage activation topics over Zenoh."""
        if self.zenoh_client.session is None:
            return

        from node.core.transport import SharedMemoryIPC, get_tensor_topic
        from node.models.sharding import LayerRange, PipelineStage, StageType, TensorPayload

        topic = "public-intelligence/net/tasks/*/tensors/*"
        loop = asyncio.get_running_loop()

        def _on_activation_sample(sample: Any) -> None:
            try:
                key_expr = str(sample.key_expr)
                parts = key_expr.split("/")
                if len(parts) < 6 or parts[-1] == "ack":
                    return

                task_id = parts[3]
                stage_idx = int(parts[5])

                if hasattr(sample.payload, "to_bytes"):
                    raw_bytes = sample.payload.to_bytes()
                elif isinstance(sample.payload, bytes):
                    raw_bytes = sample.payload
                elif isinstance(sample.payload, str):
                    raw_bytes = sample.payload.encode("utf-8")
                else:
                    raw_bytes = bytes(sample.payload)

                if raw_bytes.startswith(b"shm://"):
                    shm_name = raw_bytes[6:].decode("utf-8", errors="ignore")
                    raw_bytes = SharedMemoryIPC.read_data(shm_name)
                    SharedMemoryIPC.cleanup(shm_name)

                payload = TensorPayload.from_framed_bytes(raw_bytes)
                payload.validate_split_activation_boundary()

                async def _process_and_respond() -> None:
                    if self.inference_backend is None:
                        from node.backends.mock import EchoBackend

                        self.inference_backend = EchoBackend()

                    stage = PipelineStage(
                        stage_index=stage_idx,
                        total_stages=3,
                        layer_range=LayerRange(start_layer=1, end_layer=31),
                        node_id=self.settings.node_id,
                        model_id=self.settings.hosted_models[0]
                        if self.settings.hosted_models
                        else "default",
                        is_local_boundary=False,
                        stage_type=StageType.REMOTE_HIDDEN,
                        is_split_inference=True,
                    )
                    output_payload = await self.inference_backend.execute_split_stage(
                        stage, payload
                    )
                    output_payload.validate_split_activation_boundary()

                    out_bytes = output_payload.to_framed_bytes()
                    resp_topic = get_tensor_topic(task_id, stage_idx + 1)
                    if self.zenoh_client.session is not None:
                        self.zenoh_client.session.put(resp_topic, out_bytes)

                loop.call_soon_threadsafe(lambda: asyncio.create_task(_process_and_respond()))
            except Exception as e:
                logger.error("Error processing split stage activation sample: %s", e)

        try:
            self.split_stage_sub = self.zenoh_client.session.declare_subscriber(
                topic, _on_activation_sample
            )
        except Exception as e:
            logger.error("Failed to declare split stage subscriber: %s", e)


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    async def main() -> None:
        settings = Settings()
        runtime = Runtime(settings)
        print("🚀 Worker Node starting up...")
        await runtime.start()
        print("📢 Node registered and running background loops. Press Ctrl+C to stop.")
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            pass
        finally:
            await runtime.stop()

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Node shutting down gracefully.")
        sys.exit(0)
