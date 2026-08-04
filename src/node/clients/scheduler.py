"""Scheduler client implementation."""

import logging
from typing import Any

import httpx

from node.core.configuration import Settings
from node.models import Heartbeat, NodeInfo

logger = logging.getLogger(__name__)


class SchedulerError(Exception):
    """Exception raised for errors during Scheduler communication."""

    pass


# These two build the exact bytes that go on the wire to the Scheduler. They are
# module-level rather than inlined into the request methods so the cross-package
# contract test (`tests/test_wire_contract.py`) can feed their real output to the
# Scheduler's real models. A test that rebuilt the payload itself would only prove
# the test and the Scheduler agree, which is not the thing that breaks.


def build_registration_payload(node_info: NodeInfo) -> dict[str, Any]:
    """Serialise a NodeInfo into the body of `POST /nodes/register`.

    The Scheduler's `Node` model differs from `NodeInfo` in one way: it takes
    `available_models` as a list of names, not a list of `ModelInfo` objects.
    """
    payload = node_info.model_dump(mode="json")
    payload["available_models"] = [m["name"] for m in payload.get("available_models", [])]
    # `gpu` rides along from NodeInfo.gpu -- it used to be overwritten here with a
    # hardcoded 16 GB "unknown" card for every node on the network, which is what
    # the Scheduler then filtered and scored against. See specs/real-hardware-advertisement.md.
    return payload


def build_heartbeat_payload(heartbeat: Heartbeat) -> dict[str, Any]:
    """Serialise a Heartbeat into the body of `POST /heartbeat`.

    The Scheduler's `Heartbeat` requires a `status` the Node's model has no field
    for, so it is injected here. See specs/real-heartbeat-metrics.md -- reporting a
    real status is a known gap, not something this function decides.
    """
    payload = heartbeat.model_dump(mode="json")
    payload["status"] = "online"
    return payload


class SchedulerClient:
    """Client responsible for all communication with the Scheduler."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        """Initialize the SchedulerClient.

        Args:
            settings: Loaded configuration settings.
            client: Optional pre-configured HTTPX async client to use.
        """
        self.base_url = settings.scheduler_url.rstrip("/")
        self.client = client
        self.timeout = 5.0
        self.network_auth_token = settings.network_auth_token

    async def _send_request(
        self,
        method: str,
        path: str,
        json_data: dict[str, Any] | None = None,
    ) -> None:
        """Send an HTTP request to the Scheduler.

        Args:
            method: HTTP method (POST, DELETE, etc.).
            path: Target endpoint path (e.g. '/nodes/register').
            json_data: Optional JSON body payload.

        Raises:
            SchedulerError: If the request fails due to connection issues,
                timeouts, or non-2xx response status codes.
        """
        url = f"{self.base_url}{path}"
        headers = {}
        if self.network_auth_token:
            headers["X-Network-Auth-Token"] = self.network_auth_token

        if self.client is not None:
            try:
                response = await self.client.request(
                    method, url, json=json_data, headers=headers, timeout=self.timeout
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise SchedulerError(
                    f"Scheduler request {method} {path} failed with status "
                    f"{e.response.status_code}: {e.response.text}"
                ) from e
            except httpx.RequestError as e:
                raise SchedulerError(f"Scheduler request {method} {path} failed: {e}") from e
        else:
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.request(method, url, json=json_data, headers=headers)
                    response.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise SchedulerError(
                    f"Scheduler request {method} {path} failed with status "
                    f"{e.response.status_code}: {e.response.text}"
                ) from e
            except httpx.RequestError as e:
                raise SchedulerError(f"Scheduler request {method} {path} failed: {e}") from e

    async def register(self, node_info: NodeInfo) -> None:
        """Register the Node with the Scheduler.

        Args:
            node_info: Identity and capability specifications of the Node.

        Raises:
            SchedulerError: If registration fails.
        """
        payload = build_registration_payload(node_info)
        try:
            await self._send_request("POST", "/nodes/register", payload)
        except SchedulerError as e:
            if "409" in str(e):
                logger.info("Node already registered with Scheduler.")
            else:
                raise

    async def heartbeat(self, heartbeat: Heartbeat) -> None:
        """Send a periodic heartbeat update to the Scheduler.

        Args:
            heartbeat: Heartbeat metrics representing current utilization.

        Raises:
            SchedulerError: If the heartbeat request fails.
        """
        await self._send_request("POST", "/heartbeat", build_heartbeat_payload(heartbeat))

    async def unregister(self, node_id: str) -> None:
        """Unregister the Node from the Scheduler.

        Args:
            node_id: Unique identifier of the Node to unregister.

        Raises:
            SchedulerError: If unregistration fails.
        """
        await self._send_request("DELETE", f"/nodes/{node_id}")
