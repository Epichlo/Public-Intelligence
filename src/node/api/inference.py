"""Inference API routes."""

import uuid
from collections.abc import AsyncGenerator
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse

from node.clients import OllamaClient, OllamaError
from node.core.radix_cache import RadixTrieCache
from node.models import InferenceRequest, InferenceResponse, ModelInfo

router = APIRouter()


def get_ollama_client(request: Request) -> OllamaClient:
    """Dependency injection function to retrieve the OllamaClient instance."""
    client = getattr(request.app.state, "ollama_client", None)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OllamaClient is not initialized in application state.",
        )
    return cast(OllamaClient, client)


def get_radix_cache(request: Request) -> RadixTrieCache:
    """Dependency injection function to retrieve the global RadixTrieCache instance."""
    cache = getattr(request.app.state, "radix_cache", None)
    if cache is None:
        cache = RadixTrieCache()
        request.app.state.radix_cache = cache
    return cast(RadixTrieCache, cache)


@router.post(
    "/infer",
    response_model=InferenceResponse,
    summary="Execute inference against a local model",
)
async def infer(
    request: InferenceRequest,
    fastapi_request: Request,
    ollama_client: Annotated[OllamaClient, Depends(get_ollama_client)],
    radix_cache: Annotated[RadixTrieCache, Depends(get_radix_cache)],
) -> InferenceResponse | StreamingResponse:
    """Delegate inference to the Ollama client after prefix cache lookup."""
    original_prompt = request.prompt

    # Intercept prompt and lookup prefix
    prefix, suffix = await radix_cache.lookup_prefix(original_prompt)

    # Route only the remaining suffix data to the underlying backend serving model
    request.prompt = suffix

    # Determine client co-location based on request IP
    client_host = fastapi_request.client.host if fastapi_request.client else ""
    is_local = client_host in ("127.0.0.1", "localhost", "::1")

    # Retrieve active Zenoh session from application state runtime
    runtime = getattr(fastapi_request.app.state, "runtime", None)
    zenoh_session = None
    if runtime is not None and getattr(runtime, "zenoh_client", None) is not None:
        sess = runtime.zenoh_client.session
        if sess is not None and "mock" not in type(sess).__name__.lower():
            zenoh_session = sess

    if request.stream:
        try:
            generator = ollama_client.generate_stream(request)

            async def stream_wrapper() -> AsyncGenerator[str, None]:
                router = None
                session_id = uuid.uuid4().hex[:8]

                # Setup backpressured stream router if zenoh_session is active
                if zenoh_session is not None:
                    from node.core.transport import BackpressuredStreamRouter

                    router = BackpressuredStreamRouter(session_id, zenoh_session)
                    yield f"session_id: {session_id}\n"

                created_shms = []
                try:
                    from node.core.transport import SharedMemoryIPC

                    async for chunk in generator:
                        chunk_bytes = chunk.encode("utf-8")
                        if is_local:
                            if router is not None:
                                token_bytes = await router.send_chunk(
                                    chunk_bytes,
                                    is_local=True,
                                )
                                token = token_bytes.decode("utf-8")
                            else:
                                shm_name = SharedMemoryIPC.write_data(chunk_bytes)
                                token = f"shm://{shm_name}"
                            created_shms.append(token.split("shm://")[-1])
                            yield f"{token}\n"
                        else:
                            if router is not None:
                                await router.send_chunk(
                                    chunk_bytes,
                                    is_local=False,
                                )
                            yield chunk
                finally:
                    if router is not None:
                        router.stop()
                    from node.core.transport import SharedMemoryIPC

                    for shm in created_shms:
                        SharedMemoryIPC.cleanup(shm)
                    # Append the new total token path back to the trie upon completion
                    await radix_cache.insert_prefix(original_prompt)

            return StreamingResponse(stream_wrapper(), media_type="text/event-stream")
        except OllamaError as e:
            if "not found" in str(e).lower():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=str(e),
                ) from e
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e),
            ) from e

    try:
        response = await ollama_client.generate(request)
        # Append the new total token path back to the trie upon completion
        await radix_cache.insert_prefix(original_prompt)
        return response
    except OllamaError as e:
        if "not found" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(e),
            ) from e
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e


@router.get(
    "/models",
    response_model=list[ModelInfo],
    summary="List all hosted models",
)
async def list_models(
    ollama_client: Annotated[OllamaClient, Depends(get_ollama_client)],
) -> list[ModelInfo]:
    """Delegate model listing directly to the Ollama client."""
    try:
        return await ollama_client.list_models()
    except OllamaError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e


@router.get(
    "/health",
    summary="Get Node and Ollama health status",
)
async def health(
    ollama_client: Annotated[OllamaClient, Depends(get_ollama_client)],
) -> dict[str, Any]:
    """Check both the Node liveness and the local Ollama server connectivity."""
    is_ollama_healthy = await ollama_client.health()
    if is_ollama_healthy:
        return {"status": "healthy", "ollama": True}
    return {"status": "degraded", "ollama": False}


@router.get(
    "/health/ready",
    summary="Get Node readiness and network state",
)
async def readiness(
    fastapi_request: Request,
    response: Response,
    ollama_client: Annotated[OllamaClient, Depends(get_ollama_client)],
) -> dict[str, Any]:
    """Expose the runtime dependencies required to execute inference."""
    runtime = getattr(fastapi_request.app.state, "runtime", None)
    ollama_ready = await ollama_client.health()
    runtime_ready = runtime is not None and runtime.is_running
    scheduler_registered = (
        runtime is not None
        and runtime.is_running
        and getattr(runtime, "registration_status", None) == "registered"
    )
    wan_connected = (
        runtime is not None
        and runtime.is_running
        and getattr(runtime, "zenoh_client", None) is not None
        and runtime.zenoh_client.is_connected()
    )
    inference_ready = runtime_ready and ollama_ready and scheduler_registered
    is_ready = inference_ready
    response.status_code = (
        status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE
    )

    return {
        "status": "ready" if is_ready else "degraded",
        "runtime": runtime_ready,
        "ollama": ollama_ready,
        "scheduler_registered": scheduler_registered,
        "wan_connected": wan_connected,
        "inference_ready": inference_ready,
        "last_heartbeat_at": (
            runtime.last_heartbeat_at if runtime is not None else None
        ),
        "last_heartbeat_ok": (
            runtime.last_heartbeat_ok if runtime is not None else False
        ),
        "last_heartbeat_error": (
            runtime.last_heartbeat_error if runtime is not None else None
        ),
    }
