"""Scheduler client implementation."""

from typing import Any

import httpx

from node.core.configuration import Settings
from node.models import Heartbeat, NodeInfo


class SchedulerError(Exception):
    """Exception raised for errors during Scheduler communication."""

    pass


class SchedulerClient:
    """Client responsible for all communication with the Scheduler."""

    def __init__(
        self, settings: Settings, client: httpx.AsyncClient | None = None
    ) -> None:
        """Initialize the SchedulerClient.

        Args:
            settings: Loaded configuration settings.
            client: Optional pre-configured HTTPX async client to use.
        """
        self.base_url = settings.scheduler_url.rstrip("/")
        self.client = client
        self.timeout = 5.0

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

        if self.client is not None:
            try:
                response = await self.client.request(
                    method, url, json=json_data, timeout=self.timeout
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise SchedulerError(
                    f"Scheduler request {method} {path} failed with status "
                    f"{e.response.status_code}: {e.response.text}"
                ) from e
            except httpx.RequestError as e:
                raise SchedulerError(
                    f"Scheduler request {method} {path} failed: {e}"
                ) from e
        else:
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.request(method, url, json=json_data)
                    response.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise SchedulerError(
                    f"Scheduler request {method} {path} failed with status "
                    f"{e.response.status_code}: {e.response.text}"
                ) from e
            except httpx.RequestError as e:
                raise SchedulerError(
                    f"Scheduler request {method} {path} failed: {e}"
                ) from e

    async def register(self, node_info: NodeInfo) -> None:
        """Register the Node with the Scheduler.

        Args:
            node_info: Identity and capability specifications of the Node.

        Raises:
            SchedulerError: If registration fails.
        """
        payload = node_info.model_dump(mode="json")
        # Translate available_models from ModelInfo list to list[str] of names
        payload["available_models"] = [
            m["name"] for m in payload.get("available_models", [])
        ]
        # Inject standard GPUInfo structure required by Scheduler
        payload["gpu"] = {
            "name": "unknown",
            "vram_total_gb": 16.0,
            "vram_available_gb": 16.0,
        }
        await self._send_request("POST", "/nodes/register", payload)

    async def heartbeat(self, heartbeat: Heartbeat) -> None:
        """Send a periodic heartbeat update to the Scheduler.

        Args:
            heartbeat: Heartbeat metrics representing current utilization.

        Raises:
            SchedulerError: If the heartbeat request fails.
        """
        payload = heartbeat.model_dump(mode="json")
        # Inject NodeStatus field required by Scheduler
        payload["status"] = "online"
        await self._send_request("POST", "/heartbeat", payload)

    async def unregister(self, node_id: str) -> None:
        """Unregister the Node from the Scheduler.

        Args:
            node_id: Unique identifier of the Node to unregister.

        Raises:
            SchedulerError: If unregistration fails.
        """
        await self._send_request("DELETE", f"/nodes/{node_id}")
