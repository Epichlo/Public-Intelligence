"""Node runtime lifecycle orchestration."""

import asyncio
import logging
import os
import random
import socket
from asyncio import sleep as async_sleep
from contextlib import suppress
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any

from node.clients import OllamaClient, SchedulerClient, SchedulerError, ZenohHeartbeatClient
from node.clients.mesh_inference_server import ZenohInferenceServer
from node.core.configuration import Settings
from node.core.hardware import detect_gpu, detect_host_metrics, detect_ram_total_gb
from node.core.telemetry import TelemetryEmitter
from node.models import Heartbeat, ModelInfo, NodeInfo
from node.models.gpu_info import cpu_only_gpu

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
        self.model_refresh_task: asyncio.Task[None] | None = None
        # Runs only while registration is outstanding, and exits as soon as it lands.
        # Re-armed if the Scheduler later forgets this node -- see `_heartbeat_loop`.
        self.registration_retry_task: asyncio.Task[None] | None = None
        # The payload to re-send on a retry. Held so a retry does not re-probe
        # hardware: the figures were measured at startup and do not change while
        # this process lives, and a retry loop that re-ran nvidia-smi every few
        # seconds during an outage would be its own problem.
        self.node_info: NodeInfo | None = None
        # What the Scheduler currently believes this node can serve. Compared against
        # a fresh Ollama read each refresh so the push happens only on real change --
        # the list is near-constant, and re-sending it every interval would put it on
        # the wire thousands of times a day to say nothing.
        self.advertised_models: list[ModelInfo] = []
        # Invariant: True means the Scheduler is believed to hold exactly
        # `advertised_models`. False means we do not know what it holds -- which is
        # the state after a 409, where the record was written by an earlier process.
        # A failed push leaves both fields untouched, so the retry falls out of the
        # ordinary difference check on the next refresh.
        #
        # This exists because a difference check alone is not sufficient at startup:
        # a node whose Ollama is now empty, whose Scheduler record still lists models
        # from a previous process, would compare [] against [] and never push.
        self.catalogue_synced = False
        self.telemetry_emitter: TelemetryEmitter | None = None
        self.split_stage_sub: Any | None = None
        # Serves inference over the Zenoh session rather than over an inbound HTTP port.
        # None until start() finds a live session; see specs/node-reachability.md.
        self.mesh_inference_server: ZenohInferenceServer | None = None
        self.is_running = False

        # Was `packages/node/src/shared/`, a top-level `shared` package installed
        # into site-packages by this distribution -- so any other project shipping a
        # module by that name collided with it. It reached here through a
        # try/except ladder falling back to `src.shared...`, which only ever
        # resolved when pytest was invoked from the package directory. Moved under
        # `node.storage` so there is one import path that always works.
        #
        # ROADMAP C8 describes this module as "an orphan third copy ... imported by
        # nothing". That was wrong: it is live on the task-queue path below, where
        # every generated completion is written to disk.
        from node.backends.base import InferenceBackend
        from node.storage.local import LocalDiskArtifactStore

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
                # %s, not a structlog-style `error=` kwarg: this is a stdlib Logger,
                # which raises TypeError on unknown kwargs -- so this handler used to
                # kill startup on the exact path meant to survive Ollama being down.
                logger.warning("Ollama model discovery failed, advertising none: %s", e)
                models = []

            # 2. Discover real hardware. `detect_gpu` already degrades internally;
            # this guard is for the case where it fails in a way it did not expect,
            # because advertising nothing is better than failing to register at all.
            try:
                gpu = await detect_gpu()
            except Exception as e:
                logger.warning("Hardware discovery failed, advertising cpu-only: %s", e)
                gpu = cpu_only_gpu()

            # 2.5. Build NodeInfo
            node_info = NodeInfo(
                node_id=self.settings.node_id,
                hostname=self.settings.hostname,
                region=self.settings.region,
                ip_address=self._resolve_ip(),
                cpu_cores=self._get_cpu_cores(),
                ram_total_gb=self._get_ram_total_gb(),
                gpu=gpu,
                available_models=models,
            )

            # 3. Register with Scheduler.
            #
            # A `SchedulerError` here is NOT fatal. It used to be: it propagated out
            # of `start()`, out of the FastAPI lifespan, and uvicorn reported
            # "Application startup failed. Exiting." A host booting while the
            # Scheduler was briefly down -- a Render cold start, a network blip --
            # was left with no node process at all. Everything after this point is
            # local or mesh-side and does not need the Scheduler to exist.
            #
            # Only SchedulerError is survivable. A ValidationError from NodeInfo or a
            # TypeError in a probe is a bug in this node, and starting degraded would
            # hide it. See specs/scheduler-outage-resilience.md.
            self.node_info = node_info
            try:
                await self._attempt_registration(node_info)
            except SchedulerError as e:
                logger.warning(
                    "Scheduler unreachable at startup, starting degraded and retrying: %s", e
                )
                self.registration_status = "pending"
                self._arm_registration_retry()

            # 3.5. Start Zenoh heartbeat client
            self.zenoh_client.start()

            # 3.6. Start telemetry emitter
            if self.zenoh_client.session is not None:
                self.telemetry_emitter = TelemetryEmitter(
                    self.settings.node_id,
                    self.zenoh_client.session,
                    self.settings.network_auth_token,
                )
                self.telemetry_emitter.start()
                self._setup_split_stage_listener()

                # 3.7. Serve inference over the mesh. This is what makes a node behind
                # NAT reachable: the Scheduler queries this session instead of dialling
                # an inbound port that does not exist.
                self.mesh_inference_server = ZenohInferenceServer(
                    self.settings, self.zenoh_client.session, self.ollama_client
                )
                self.mesh_inference_server.start()

            # 4. Start periodic heartbeats
            self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())

            # 4.5. Start periodic model-catalogue refresh, so `ollama pull` and
            # `ollama rm` reach the Scheduler without restarting the node.
            self.model_refresh_task = asyncio.create_task(self._model_refresh_loop())

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

        # Stop accepting mesh inference queries, then give any already being answered a
        # brief chance to reply rather than dropping a request the caller is waiting on.
        if self.mesh_inference_server is not None:
            with suppress(Exception):
                self.mesh_inference_server.stop()
            with suppress(Exception):
                await self.mesh_inference_server.wait_for_inflight(timeout=5.0)
            self.mesh_inference_server = None

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

        # Cancel the registration retry task. Normally already finished -- it exits as
        # soon as registration lands -- but a node stopped during an outage is exactly
        # the case where it is still sleeping on a backoff.
        if self.registration_retry_task is not None:
            self.registration_retry_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.registration_retry_task
            self.registration_retry_task = None

        # Cancel background model-catalogue refresh task
        if self.model_refresh_task is not None:
            self.model_refresh_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.model_refresh_task
            self.model_refresh_task = None

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
            # Nothing to heartbeat to yet. `/heartbeat` 404s for a node the registry
            # does not know, so posting while registration is outstanding would log an
            # error every interval and say nothing the retry loop is not already
            # handling. See specs/scheduler-outage-resilience.md.
            if self.registration_status != "registered":
                try:
                    await async_sleep(self.settings.heartbeat_interval_seconds)
                except asyncio.CancelledError:
                    break
                continue

            try:
                metrics = await self._collect_heartbeat_metrics()
                hb = Heartbeat(
                    node_id=self.settings.node_id,
                    timestamp=datetime.now(UTC),
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
            except SchedulerError as e:
                self.last_heartbeat_ok = False
                self.last_heartbeat_error = str(e)

                # 404 means the Scheduler no longer has a record for this node -- it
                # restarted and lost its in-memory registry (ROADMAP 2.1), or evicted
                # this node as stale. Without this, the node heartbeats into a 404
                # every interval for the rest of its life and is never matchmade
                # again; the only recovery was a manual restart.
                if e.status_code == HTTPStatus.NOT_FOUND:
                    logger.warning("Scheduler has forgotten this node, re-registering: %s", e)
                    self.registration_status = "pending"
                    self._arm_registration_retry()
                else:
                    logger.error("Failed to send heartbeat: %s", e)
            except Exception as e:
                self.last_heartbeat_ok = False
                self.last_heartbeat_error = str(e)
                logger.error("Failed to send heartbeat: %s", e)

            try:
                await async_sleep(self.settings.heartbeat_interval_seconds)
            except asyncio.CancelledError:
                break

    async def _attempt_registration(self, node_info: NodeInfo) -> None:
        """Register once and reconcile the catalogue. Raises SchedulerError on failure.

        Shared by `start()` and the retry loop so a late registration leaves exactly
        the same state as an on-time one -- in particular so a node that registers
        after an outage still corrects a catalogue an earlier process left behind.
        """
        created = await self.scheduler_client.register(node_info)
        self.registration_status = "registered"

        if created:
            # The registration payload carried the catalogue, so the Scheduler's
            # view and ours agree by construction.
            self.advertised_models = node_info.available_models
            self.catalogue_synced = True
        else:
            # A 409 means the Scheduler already had a record for this node_id,
            # written by an *earlier* process and carrying that process's model
            # catalogue. Registration cannot correct it -- it is a create, and the
            # 409 is swallowed -- and heartbeats carry no model list, so without
            # this push a node that restarts after an `ollama pull` stays
            # misadvertised for as long as the Scheduler lives. If the push fails,
            # `catalogue_synced` stays False and the refresh loop keeps retrying.
            await self._publish_model_catalogue(node_info.available_models)

    def _arm_registration_retry(self) -> None:
        """Start the retry loop, unless one is already running."""
        if self.registration_retry_task is not None and not self.registration_retry_task.done():
            return
        self.registration_retry_task = asyncio.create_task(self._registration_retry_loop())

    async def _registration_retry_loop(self) -> None:
        """Retry registration with exponential backoff until it succeeds.

        There is no attempt limit. A node whose Scheduler is down for a day should
        join when it comes back, not give up and require a manual restart -- the
        absence of any recovery path is the whole defect being fixed here.

        The delay is full jitter: `uniform(0, interval)` rather than `interval`. The
        situation that produces this is a Scheduler that was down and returned, which
        means every node in the fleet is retrying at the same moment; plain
        exponential backoff keeps them synchronised and lands the herd on a service
        that has only just started. (`random` here picks a sleep duration. It is not
        used for anything that needs to be unpredictable.)
        """
        interval = 1.0
        while self.is_running and self.registration_status != "registered":
            delay = random.uniform(0, min(interval, self.settings.registration_retry_max_seconds))
            try:
                await async_sleep(delay)
            except asyncio.CancelledError:
                break

            if not self.is_running or self.node_info is None:
                break

            try:
                await self._attempt_registration(self.node_info)
            except SchedulerError as e:
                interval = min(interval * 2, self.settings.registration_retry_max_seconds)
                logger.warning(
                    "Registration retry failed, next attempt in <=%.1fs: %s", interval, e
                )
                continue
            except asyncio.CancelledError:
                break

            logger.info("Registered with Scheduler after retrying: %s", self.settings.node_id)
            return

    async def _model_refresh_loop(self) -> None:
        """Periodically re-read Ollama's model list and push it if it changed.

        Ollama has no change-notification API, so this polls. The interval is
        therefore the staleness bound: worst case, the Scheduler is wrong about this
        node's catalogue for `model_refresh_interval_seconds` after an `ollama pull`
        or `ollama rm`. See specs/truthful-model-catalogue.md.
        """
        while self.is_running:
            # Sleep first: the catalogue was read moments ago in `start()`, so an
            # immediate refresh would be a guaranteed no-op call to Ollama.
            try:
                await async_sleep(self.settings.model_refresh_interval_seconds)
            except asyncio.CancelledError:
                break
            if not self.is_running:
                break
            # `PUT /nodes/{id}/models` 404s for a node the Scheduler does not know.
            # Registration reconciles the catalogue itself when it lands, so there is
            # nothing for this loop to do until then.
            if self.registration_status != "registered":
                continue
            await self._refresh_model_catalogue()

    async def _refresh_model_catalogue(self) -> None:
        """Read the current catalogue and push it to the Scheduler if it differs."""
        try:
            models = await self.ollama_client.list_models()
        except Exception as e:
            # Keep advertising the previous catalogue. "I cannot reach Ollama right
            # now" is not "I have no models": treating it as such would unadvertise
            # the whole node on a transient blip and re-advertise seconds later,
            # flapping the fleet catalogue and dropping the node out of matchmaking
            # for no reason. This is the opposite of the startup path, where
            # advertising nothing is correct because nothing has been advertised yet.
            logger.warning("Model refresh failed, keeping the advertised catalogue: %s", e)
            return

        # Names, not ModelInfo objects: names are all the Scheduler stores, so a
        # changed `size_gb` is not a change to anything it can act on. Sorted, because
        # a reordering of the same models is likewise not a change -- the matchmaker
        # does membership tests and `/v1/models` sorts.
        if self.catalogue_synced and self._model_names(models) == self._model_names(
            self.advertised_models
        ):
            return

        await self._publish_model_catalogue(models)

    @staticmethod
    def _model_names(models: list[ModelInfo]) -> list[str]:
        """Return the comparable identity of a catalogue: its model names, sorted."""
        return sorted(m.name for m in models)

    async def _publish_model_catalogue(self, models: list[ModelInfo]) -> bool:
        """Send `models` to the Scheduler, recording them as advertised only if it lands.

        A failed push must not update `advertised_models` or set `catalogue_synced`.
        If it did, the node would believe the Scheduler agrees with it and would never
        retry -- leaving the fleet catalogue permanently wrong after one dropped
        request. Returns whether the push succeeded.
        """
        try:
            await self.scheduler_client.update_models(self.settings.node_id, models)
        except Exception as e:
            logger.warning("Failed to publish model catalogue, will retry: %s", e)
            return False

        self.advertised_models = models
        self.catalogue_synced = True
        logger.info(
            "Published model catalogue for node %s: %s",
            self.settings.node_id,
            self._model_names(models),
        )
        return True

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
        """Retrieve total system RAM in gigabytes, measured from the host."""
        return detect_ram_total_gb()

    async def _collect_heartbeat_metrics(self) -> dict[str, Any]:
        """Measure current utilisation for a heartbeat report.

        These are not cosmetic. The Scheduler filters on `vram_available_gb` and
        scores nodes on all five, so the constants this used to return meant a node
        was excluded from every VRAM-gated task and scored identically to every
        other node. See specs/real-heartbeat-metrics.md.

        `detect_host_metrics` degrades internally rather than raising, so a host that
        cannot read its own GPU keeps heartbeating instead of being evicted as stale.
        """
        metrics = await detect_host_metrics()
        return {
            "queue_length": self.task_queue.qsize(),
            "cpu_utilization": metrics.cpu_utilization,
            "ram_available_gb": metrics.ram_available_gb,
            "gpu_utilization": metrics.gpu_utilization,
            "vram_available_gb": metrics.vram_available_gb,
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
                        # A label, not a routing decision -- this stage is handed to
                        # `inference_backend`, which is only ever EchoBackend. It used
                        # to read `settings.hosted_models[0]`, a config-declared model
                        # list that no node actually set; "default" is what every such
                        # node already produced here.
                        model_id="default",
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
