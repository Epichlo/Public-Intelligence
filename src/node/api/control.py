"""Host node control, telemetry, and sandbox log monitoring endpoints."""

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from node.core.runtime import sandbox_log_buffer
from node.telemetry.collector import TelemetryCollector

router = APIRouter()


class NodeControlRequest(BaseModel):
    """Request payload for node control endpoint."""

    action: str = Field(..., description="Action to perform: 'start' or 'stop'")


class NodeControlResponse(BaseModel):
    """Response payload for node control endpoint."""

    status: str
    action: str
    runtime_running: bool


class NodeTelemetryResponse(BaseModel):
    """Response payload for local node telemetry endpoint."""

    node_id: str
    cpu_utilization: float
    ram_used_bytes: int
    ram_total_bytes: int
    gpu_utilization: float
    vram_used_bytes: int
    vram_total_bytes: int
    wan_connected: bool
    status: str


@router.get(
    "/api/v1/node/telemetry",
    response_model=NodeTelemetryResponse,
    summary="Get real-time local node hardware telemetry and P2P state",
)
async def get_node_telemetry(fastapi_request: Request) -> NodeTelemetryResponse:
    """Retrieve real-time host hardware metrics and P2P connection status."""
    runtime = getattr(fastapi_request.app.state, "runtime", None)

    node_id = "unknown-node"
    if runtime is not None and getattr(runtime, "settings", None) is not None:
        node_id = runtime.settings.node_id
    else:
        from node.core.configuration import get_settings

        node_id = get_settings().node_id

    collector = TelemetryCollector()
    metrics = await collector.collect()

    zenoh_client = (
        getattr(runtime, "zenoh_client", None) if runtime is not None else None
    )
    wan_connected = False
    if runtime is not None and runtime.is_running and zenoh_client is not None:
        conn = zenoh_client.is_connected()
        wan_connected = bool(await conn) if asyncio.iscoroutine(conn) else bool(conn)

    status_str = "ready" if (runtime is not None and runtime.is_running) else "stopped"

    return NodeTelemetryResponse(
        node_id=node_id,
        cpu_utilization=float(metrics.get("cpu_utilization", 0.0)),
        ram_used_bytes=int(metrics.get("ram_used_bytes", 0)),
        ram_total_bytes=int(metrics.get("ram_total_bytes", 0)),
        gpu_utilization=float(metrics.get("gpu_utilization", 0.0)),
        vram_used_bytes=int(metrics.get("vram_used_bytes", 0)),
        vram_total_bytes=int(metrics.get("vram_total_bytes", 0)),
        wan_connected=wan_connected,
        status=status_str,
    )


@router.post(
    "/api/v1/node/control",
    response_model=NodeControlResponse,
    summary="Control host node execution runtime status (start/stop)",
)
async def control_node(
    payload: NodeControlRequest,
    fastapi_request: Request,
) -> NodeControlResponse:
    """Trigger host node runtime start/stop execution sequence."""
    action = payload.action.strip().lower()
    if action not in ("start", "stop"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid action. Must be 'start' or 'stop'.",
        )

    runtime = getattr(fastapi_request.app.state, "runtime", None)
    if runtime is None:
        from node.core.configuration import get_settings
        from node.runtime import Runtime

        runtime = Runtime(get_settings())
        fastapi_request.app.state.runtime = runtime

    if action == "start" and not runtime.is_running:
        await runtime.start()
    elif action == "stop" and runtime.is_running:
        await runtime.stop()

    return NodeControlResponse(
        status="ok",
        action=action,
        runtime_running=runtime.is_running,
    )


@router.get(
    "/api/v1/sandbox/logs",
    summary="Get recent Docker sandbox execution logs",
)
async def get_sandbox_logs(limit: int = 100) -> dict[str, Any]:
    """Retrieve recent Docker sandbox container execution log entries."""
    entries = sandbox_log_buffer.get_logs(limit=limit)
    formatted_logs = [
        f"[{e['timestamp']}] [{e['stream']}] {e['message']}" for e in entries
    ]
    return {
        "logs": formatted_logs,
        "entries": entries,
    }


@router.get(
    "/api/v1/sandbox/logs/stream",
    summary="Stream real-time Docker sandbox execution logs as SSE",
)
async def stream_sandbox_logs(
    fastapi_request: Request,
    max_events: int | None = None,
) -> StreamingResponse:
    """Stream real-time Docker sandbox execution logs as SSE events."""

    async def log_generator() -> AsyncGenerator[str, None]:
        queue = sandbox_log_buffer.subscribe()
        count = 0
        try:
            for entry in sandbox_log_buffer.get_logs(limit=50):
                formatted = (
                    f"[{entry['timestamp']}] [{entry['stream']}] {entry['message']}"
                )
                payload = json.dumps({"entry": entry, "log": formatted})
                yield f"data: {payload}\n\n"
                count += 1
                if max_events is not None and count >= max_events:
                    return

            while True:
                if await fastapi_request.is_disconnected():
                    break
                try:
                    entry = await asyncio.wait_for(queue.get(), timeout=0.1)
                    formatted = (
                        f"[{entry['timestamp']}] [{entry['stream']}] {entry['message']}"
                    )
                    payload = json.dumps({"entry": entry, "log": formatted})
                    yield f"data: {payload}\n\n"
                    count += 1
                    if max_events is not None and count >= max_events:
                        break
                except asyncio.TimeoutError:
                    if max_events is not None:
                        break
                    yield ": keep-alive\n\n"
        finally:
            sandbox_log_buffer.unsubscribe(queue)

    return StreamingResponse(log_generator(), media_type="text/event-stream")
