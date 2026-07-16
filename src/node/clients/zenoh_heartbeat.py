"""Zenoh client for publishing Node heartbeats."""

import json
import logging
from typing import Any

import zenoh

from node.core.configuration import Settings
from node.models import Heartbeat

logger = logging.getLogger(__name__)


class ZenohHeartbeatClient:
    """Manages publishing node heartbeats to the Scheduler over Zenoh."""

    def __init__(self, settings: Settings) -> None:
        """Initialize the ZenohHeartbeatClient.

        Args:
            settings: Loaded configuration settings.
        """
        self.settings = settings
        self.session: zenoh.Session | None = None
        self.publisher: zenoh.Publisher | None = None
        self.liveliness_token: Any = None
        self._key_expr = f"public-intelligence/net/{self.settings.node_id}/heartbeat"

    def start(self) -> None:
        """Open the Zenoh session and declare the publisher."""
        if self.session is not None:
            return

        logger.info("Opening Zenoh session for heartbeat publication...")
        try:
            # Open default Zenoh session
            # (configured for WAN mesh discovery by default)
            self.session = zenoh.open(zenoh.Config())
            self.publisher = self.session.declare_publisher(self._key_expr)

            # Declare liveliness token
            token_path = f"public-intelligence/net/liveliness/{self.settings.node_id}"
            self.liveliness_token = self.session.liveliness().declare_token(token_path)

            logger.info(
                "Zenoh session opened and publisher/liveliness declared on key: %s",
                self._key_expr,
            )
        except Exception as e:
            logger.error("Failed to initialize Zenoh session: %s", e)
            self.session = None
            self.publisher = None
            self.liveliness_token = None
            raise

    def stop(self) -> None:
        """Close the Zenoh session and clean up."""
        if self.session is None:
            return

        logger.info("Closing Zenoh session...")
        try:
            if self.liveliness_token is not None:
                self.liveliness_token.undeclare()
                self.liveliness_token = None
            if self.publisher is not None:
                self.publisher.undeclare()  # type: ignore[no-untyped-call]
                self.publisher = None
            self.session.close()  # type: ignore[no-untyped-call]
        except Exception as e:
            logger.error("Error closing Zenoh session: %s", e)
        finally:
            self.session = None
            self.liveliness_token = None
            logger.info("Zenoh session closed.")

    def publish(self, heartbeat: Heartbeat) -> None:
        """Publish a heartbeat message to the Zenoh network.

        Args:
            heartbeat: Heartbeat metrics representing current utilization.

        Raises:
            RuntimeError: If Zenoh session is not active.
        """
        if self.session is None or self.publisher is None:
            raise RuntimeError("Zenoh session is not active. Call start() first.")

        payload_dict = heartbeat.model_dump(mode="json")
        # Ensure status field is included and online (to match scheduler requirements)
        payload_dict["status"] = "online"

        payload_str = json.dumps(payload_dict)
        logger.debug("Publishing heartbeat payload via Zenoh: %s", payload_str)
        self.publisher.put(payload_str)
