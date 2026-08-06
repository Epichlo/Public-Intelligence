"""Zenoh router implementation for receiving node heartbeats."""

import asyncio
import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
import zenoh

from scheduler.core.consensus import RaftConsensusEngine
from scheduler.core.mesh_auth import (
    PURPOSE_HEARTBEAT,
    PURPOSE_TELEMETRY,
    MeshAuthError,
    open_envelope,
)
from scheduler.models.heartbeat import Heartbeat
from scheduler.registry.node_registry import NodeRegistry

logger = structlog.stdlib.get_logger()


class ZenohRouter:
    """Listens for incoming node heartbeats over Zenoh and routes them to NodeRegistry."""

    def __init__(self, registry: NodeRegistry, config: zenoh.Config | None = None) -> None:
        """Initialize the ZenohRouter.

        Args:
            registry: The NodeRegistry where heartbeats should be updated.
            config: Optional Zenoh session configuration.
        """
        self.registry = registry
        if config is None:
            from scheduler.core.config import get_settings

            settings = get_settings()
            config = zenoh.Config()
            if settings.zenoh_listen_endpoints:
                config.insert_json5("listen/endpoints", json.dumps(settings.zenoh_listen_endpoints))
                config.insert_json5("mode", '"router"')

            connect_endpoints: list[str] = []
            candidates: list[str] = list(settings.zenoh_peer_endpoints) + list(
                settings.bootstrap_routers
            )
            for ep in candidates:
                if ep and ep not in connect_endpoints:
                    connect_endpoints.append(ep)

            if connect_endpoints:
                config.insert_json5("connect/endpoints", json.dumps(connect_endpoints))

            if not settings.zenoh_multicast_scouting:
                config.insert_json5("scouting/multicast/enabled", "false")

            gossip_enabled = "true" if settings.zenoh_gossip_scouting else "false"
            config.insert_json5("scouting/gossip/enabled", gossip_enabled)
        self.config = config
        self.session: zenoh.Session | None = None
        self.subscriber: zenoh.Subscriber[Any] | None = None
        self.liveliness_subscriber: zenoh.Subscriber[Any] | None = None
        self.telemetry_subscriber: zenoh.Subscriber[Any] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

        # When each node last sent a heartbeat that VERIFIED. This is the clock the
        # stale sweep runs on, and it is deliberately not the registry's heartbeat
        # store: that holds whatever was last accepted, whereas eviction must key on
        # proof of liveness. `monotonic`, so a system clock change cannot evict the
        # fleet.
        self._last_verified_heartbeat: dict[str, float] = {}
        self._sweep_task: asyncio.Task[None] | None = None

        from scheduler.core.config import get_settings as _get_settings

        _settings = _get_settings()
        self.node_stale_after_seconds = _settings.node_stale_after_seconds
        self.stale_sweep_interval_seconds = _settings.stale_sweep_interval_seconds

        # Generate unique scheduler ID and instantiate the consensus engine
        scheduler_id = f"scheduler-{uuid.uuid4().hex[:8]}"
        self.consensus_engine = RaftConsensusEngine(scheduler_id, self.registry, self.config)
        self._background_tasks: set[asyncio.Task[Any]] = set()

    def start(self) -> None:
        """Start the Zenoh router session and declare the subscriber."""
        if self.session is not None:
            return

        self._loop = asyncio.get_running_loop()
        logger.info("zenoh_router_starting", key_expr="public-intelligence/net/*/heartbeat")

        # Open a Zenoh session with configured settings
        try:
            self.session = zenoh.open(self.config)
        except zenoh.ZError as err:
            logger.warning("zenoh_router_open_failed: %s", err)
            self.session = None
            return

        # Subscribe to heartbeat path.
        # Zenoh python subscriber takes a callback.
        self.subscriber = self.session.declare_subscriber(
            "public-intelligence/net/*/heartbeat", self._on_heartbeat
        )

        # Subscribe to liveliness tokens.
        # Zenoh liveliness subscriber detects PUT/DELETE events for liveliness tokens.
        self.liveliness_subscriber = self.session.liveliness().declare_subscriber(
            "public-intelligence/net/liveliness/*", self._on_liveliness
        )

        # Subscribe to telemetry feed.
        self.telemetry_subscriber = self.session.declare_subscriber(
            "public-intelligence/net/nodes/*/telemetry", self._on_telemetry
        )

        # Start consensus engine
        start_task = asyncio.create_task(self.consensus_engine.start())
        self._background_tasks.add(start_task)
        start_task.add_done_callback(self._background_tasks.discard)

        # Age nodes out. Nothing did this before -- a host left the registry only by
        # unregistering gracefully or by an UNAUTHENTICATED liveliness deathrattle,
        # which is the eviction hole 2.7 closes. Removing that hole without this
        # would trade it for dead hosts advertised forever.
        self._sweep_task = asyncio.create_task(self._stale_sweep_loop())

        logger.info("zenoh_router_started")

    def stop(self) -> None:
        """Stop and clean up the Zenoh router session."""
        if self.session is None:
            return

        logger.info("zenoh_router_stopping")
        if self._sweep_task is not None:
            self._sweep_task.cancel()
            self._sweep_task = None

        if self.subscriber is not None:
            self.subscriber.undeclare()  # type: ignore[no-untyped-call]
            self.subscriber = None

        if self.liveliness_subscriber is not None:
            self.liveliness_subscriber.undeclare()  # type: ignore[no-untyped-call]
            self.liveliness_subscriber = None

        if self.telemetry_subscriber is not None:
            self.telemetry_subscriber.undeclare()  # type: ignore[no-untyped-call]
            self.telemetry_subscriber = None

        # Stop consensus engine
        stop_task = asyncio.create_task(self.consensus_engine.stop())
        self._background_tasks.add(stop_task)
        stop_task.add_done_callback(self._background_tasks.discard)

        self.session.close()  # type: ignore[no-untyped-call]
        self.session = None
        self._loop = None
        logger.info("zenoh_router_stopped")

    def _on_heartbeat(self, sample: zenoh.Sample) -> None:
        """Callback triggered when a heartbeat is received on the zenoh session.

        Runs in Zenoh's internal thread pool, so we dispatch the async work
        to the running asyncio event loop.
        """
        if self._loop is None or not self._loop.is_running():
            return

        # Attempt to decode sample.payload safely
        try:
            payload_str = sample.payload.to_string()
        except AttributeError:
            try:
                payload_str = sample.payload.decode("utf-8")  # type: ignore[attr-defined]
            except (AttributeError, UnicodeDecodeError):
                payload_str = str(sample.payload)

        # Schedule the processing on the asyncio event loop thread-safely
        self._loop.call_soon_threadsafe(
            lambda: asyncio.create_task(self._process_heartbeat(payload_str, str(sample.key_expr)))
        )

    def _node_id_from_topic(self, key_expr: str, index: int) -> str | None:
        """Read the node id out of a key expression.

        The TOPIC is the only trustworthy source of the sender's claimed identity,
        because it is what selects the key the envelope is verified against. A
        node_id read out of the message body would let a publisher pick which key
        the Scheduler used to check its own forgery.
        """
        parts = key_expr.split("/")
        if len(parts) <= index or not parts[index]:
            logger.warning("zenoh_unparseable_topic", key_expr=key_expr)
            return None
        return parts[index]

    async def _open_from_node(self, raw: str, node_id: str, purpose: str, key_expr: str) -> Any:
        """Verify and decrypt a mesh envelope, or return None and log why.

        Returns None -- rather than raising -- for every failure, including an
        unregistered node or one with no stored credential. Both are ordinary
        states: registration is a separate HTTP call, and after ROADMAP 1.6 a node
        the Scheduler does not know re-registers on a jittered backoff. Accepting
        unverifiable data to cover that window would reopen the hole this closes.
        """
        if not await self.registry.exists(node_id):
            logger.debug("zenoh_ingress_unregistered_node", node_id=node_id, key_expr=key_expr)
            return None

        token = self.registry.get_node_token(node_id)
        if not token:
            logger.warning(
                "zenoh_ingress_no_credential_for_node", node_id=node_id, key_expr=key_expr
            )
            return None

        try:
            return open_envelope(raw, node_id=node_id, token=token, purpose=purpose)
        except MeshAuthError as e:
            logger.error(
                "security_breach_warning",
                reason=f"mesh envelope failed verification: {e}",
                node_id=node_id,
                purpose=purpose,
                key_expr=key_expr,
            )
            return None

    async def _process_heartbeat(self, payload_str: str, key_expr: str) -> None:
        """Verify, decrypt, and apply a heartbeat.

        Heartbeats used to be accepted as plain unsigned JSON, while the telemetry
        beside them was at least encrypted. `filter_nodes` compares the heartbeat's
        `vram_available_gb` against a task's `min_vram_gb`, so forging one moved any
        node in or out of every dispatch. See specs/authenticated-mesh-ingress.md.
        """
        node_id = self._node_id_from_topic(key_expr, 2)
        if node_id is None:
            return

        data = await self._open_from_node(payload_str, node_id, PURPOSE_HEARTBEAT, key_expr)
        if data is None:
            return

        try:
            heartbeat = Heartbeat(**data)
        except Exception as e:
            logger.error("zenoh_heartbeat_validation_error", error=str(e), key_expr=key_expr)
            return

        if heartbeat.node_id != node_id:
            logger.error(
                "security_breach_warning",
                reason="heartbeat body names a different node than its topic",
                body_node_id=heartbeat.node_id,
                topic_node_id=node_id,
            )
            return

        try:
            await self.registry.update_heartbeat(heartbeat)
        except ValueError as e:
            logger.warning(
                "zenoh_heartbeat_ignored_unregistered_node",
                node_id=heartbeat.node_id,
                error=str(e),
                key_expr=key_expr,
            )
            return

        # A VERIFIED heartbeat is the only thing that proves a node holds a live
        # session, which is what makes it dispatchable over the mesh rather than by
        # dialling an `ip_address` that is 127.0.0.1 for every installer-provisioned
        # node. It is also the clock the stale sweep runs on.
        self.registry.mark_mesh_reachable(heartbeat.node_id)
        self._last_verified_heartbeat[heartbeat.node_id] = time.monotonic()
        logger.info("zenoh_heartbeat_processed", node_id=heartbeat.node_id, key_expr=key_expr)

    def _on_liveliness(self, sample: zenoh.Sample) -> None:
        """Callback triggered when a liveliness token is updated (PUT/DELETE).

        We process DELETE events as node deathrattles to trigger self-correcting unregistration.
        """
        if self._loop is None or not self._loop.is_running():
            return

        key_expr = str(sample.key_expr)
        # key_expr format: public-intelligence/net/liveliness/<node_id>
        parts = key_expr.split("/")
        if len(parts) < 4:
            return
        node_id = parts[3]

        if sample.kind == zenoh.SampleKind.DELETE:
            self._loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self._process_deathrattle(node_id, key_expr))
            )
        else:
            # A PUT means the node has just declared its liveliness token, which is the
            # earliest evidence it is on the mesh -- it arrives before the first heartbeat.
            self._loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self._process_liveliness_alive(node_id, key_expr))
            )

    # A liveliness token carries NO PAYLOAD, so there is nothing to sign and the
    # node id comes from a key expression the publisher chose. Both handlers below
    # therefore observe and log; neither writes registry state.
    #
    # The rule: an unauthenticated signal may accelerate a check, never perform a
    # write. Marking reachability from a PUT cost a real request -- dispatch would
    # prefer a mesh queryable that does not exist and wait
    # `mesh_inference_first_reply_timeout_seconds` before falling back. Unregistering
    # on a DELETE was worse: declaring a liveliness token for someone else's node id
    # and dropping it evicted that host from the network.

    async def _process_liveliness_alive(self, node_id: str, key_expr: str) -> None:
        """Note that something claims `node_id` is alive. Changes nothing.

        Reachability now comes only from a VERIFIED heartbeat, which arrives within
        one heartbeat interval and actually proves the node holds the session.
        """
        logger.debug("zenoh_liveliness_alive_observed", node_id=node_id, key_expr=key_expr)

    async def _process_deathrattle(self, node_id: str, key_expr: str) -> None:
        """Treat a dropped liveliness token as a reason to check, not to evict.

        If the node has heartbeated recently and verifiably, this is noise -- or a
        forgery -- and nothing happens. If it has not, it was already due for
        eviction and this only means the sweep reaches that conclusion now instead
        of at its next tick.
        """
        logger.info("zenoh_liveliness_deathrattle_detected", node_id=node_id, key_expr=key_expr)
        await self._evict_if_stale(node_id)

    async def _evict_if_stale(self, node_id: str) -> bool:
        """Remove `node_id` if no verified heartbeat has arrived recently.

        Returns True if the node was evicted.
        """
        last_seen = self._last_verified_heartbeat.get(node_id)
        age = None if last_seen is None else time.monotonic() - last_seen
        if age is not None and age < self.node_stale_after_seconds:
            logger.debug("zenoh_node_still_fresh", node_id=node_id, seconds_since_heartbeat=age)
            return False

        if not await self.registry.exists(node_id):
            return False

        await self.registry.unregister_node(node_id)
        self._last_verified_heartbeat.pop(node_id, None)
        logger.info(
            "zenoh_node_evicted_stale",
            node_id=node_id,
            seconds_since_heartbeat=age,
            threshold=self.node_stale_after_seconds,
        )
        return True

    async def _sweep_stale_nodes(self) -> None:
        """Evict every node whose last verified heartbeat is too old.

        This is the mechanism ROADMAP 2.5 described as already existing. It did
        not: nothing in the Scheduler aged nodes out, so a host only left the
        registry by unregistering gracefully or by an unauthenticated deathrattle.
        """
        for node in await self.registry.list():
            await self._evict_if_stale(node.node_id)

    async def _stale_sweep_loop(self) -> None:
        """Run the sweep on an interval for the life of the router."""
        while True:
            await asyncio.sleep(self.stale_sweep_interval_seconds)
            try:
                await self._sweep_stale_nodes()
            except Exception:
                # One bad sweep must not kill the only thing aging nodes out.
                logger.exception("zenoh_stale_sweep_failed")

    def _on_telemetry(self, sample: zenoh.Sample) -> None:
        """Callback triggered when telemetry is received on the zenoh session."""
        if self._loop is None or not self._loop.is_running():
            return

        try:
            payload_str = sample.payload.to_string()
        except AttributeError:
            try:
                payload_str = sample.payload.decode("utf-8")  # type: ignore[attr-defined]
            except (AttributeError, UnicodeDecodeError):
                payload_str = str(sample.payload)

        self._loop.call_soon_threadsafe(
            lambda: asyncio.create_task(self._process_telemetry(payload_str, str(sample.key_expr)))
        )

    async def _process_telemetry(self, payload_str: str, key_expr: str) -> None:
        """Verify, decrypt, and map node telemetry into the registry.

        Telemetry feeds `matchmaker.score_nodes` -- `reliability`, `queue_depth` and
        `cpu` -- and `filter_nodes` via `backend_type`. It used to be signed with a
        fleet-wide key whose default was a constant published in this repository, so
        `reliability_score: 999` from anyone on the mesh won every dispatch.
        See specs/authenticated-mesh-ingress.md.
        """
        node_id = self._node_id_from_topic(key_expr, 3)
        if node_id is None:
            return

        data = await self._open_from_node(payload_str, node_id, PURPOSE_TELEMETRY, key_expr)
        if data is None:
            return

        # Freshness. Kept from the previous implementation: authentication proves
        # WHO sent it, not WHEN -- an envelope captured off the wire is still
        # replayable inside this window, which the spec records as out of scope.
        raw_ts = data.get("timestamp")
        if raw_ts is None:
            logger.warning("zenoh_telemetry_missing_timestamp", key_expr=key_expr)
            return

        ts_dt: datetime | None = None
        if isinstance(raw_ts, (int, float)):
            ts_dt = datetime.fromtimestamp(raw_ts, tz=UTC)
        elif isinstance(raw_ts, str):
            try:
                ts_dt = datetime.fromisoformat(raw_ts)
                if ts_dt.tzinfo is None:
                    ts_dt = ts_dt.replace(tzinfo=UTC)
            except ValueError:
                ts_dt = None

        if ts_dt is None:
            logger.warning(
                "zenoh_telemetry_invalid_timestamp_format", timestamp=raw_ts, key_expr=key_expr
            )
            return

        age = (datetime.now(tz=UTC) - ts_dt).total_seconds()
        if age > 30.0 or age < -10.0:
            logger.warning("zenoh_telemetry_stale_timestamp", age=age, key_expr=key_expr)
            return

        # Identity comes from the TOPIC, never the body -- the topic is what chose
        # the key this envelope verified against. The old fallback read `parts[4]`
        # of `.../nodes/<id>/telemetry`, which is the literal string "telemetry".
        self.registry._telemetry[node_id] = data
        self.registry.mark_mesh_reachable(node_id)
        logger.info("zenoh_telemetry_mapped", node_id=node_id, key_expr=key_expr)
