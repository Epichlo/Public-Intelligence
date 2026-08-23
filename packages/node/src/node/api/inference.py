"""Inference API routes."""

import json
from collections.abc import AsyncGenerator
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse

from node.api.auth import verify_node_auth
from node.clients import OllamaClient, OllamaError
from node.core.completion_cache import CompletionCache
from node.models import InferenceRequest, InferenceResponse, ModelInfo

router = APIRouter()


def _sse_error_frame(status_code: int, message: str) -> str:
    """Build one terminal SSE frame reporting a stream that ended early.

    Shaped like the mesh protocol's encode_error payload ({"ok", "status",
    "error"}): no chunk Ollama emits ever carries an "ok" key, so a parser
    can distinguish this frame from every legitimate end-of-stream.
    """
    return f"data: {json.dumps({'ok': False, 'status': status_code, 'error': message})}\n\n"


def get_ollama_client(request: Request) -> OllamaClient:
    """Dependency injection function to retrieve the OllamaClient instance."""
    client = getattr(request.app.state, "ollama_client", None)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OllamaClient is not initialized in application state.",
        )
    return cast("OllamaClient", client)


def get_completion_cache(request: Request) -> CompletionCache:
    """Dependency injection function to retrieve the global CompletionCache instance."""
    cache = getattr(request.app.state, "completion_cache", None)
    if cache is None:
        cache = CompletionCache()
        request.app.state.completion_cache = cache
    return cache


# Protected per route rather than router-wide: /health and /health/ready below
# must stay reachable without credentials for container HEALTHCHECK and liveness
# probes. /infer spends the host's GPU, so it is not left open.
@router.post(
    "/infer",
    response_model=InferenceResponse,
    summary="Execute inference against a local model",
    dependencies=[Depends(verify_node_auth)],
)
async def infer(
    request: InferenceRequest,
    ollama_client: Annotated[OllamaClient, Depends(get_ollama_client)],
    completion_cache: Annotated[CompletionCache, Depends(get_completion_cache)],
) -> InferenceResponse | StreamingResponse:
    """Delegate inference to the Ollama client, memoizing whole completions."""
    # Streaming responses are never replayed from the memo: a cached hit would
    # collapse the token stream into one chunk and change the shape callers
    # see. Streamed requests therefore always run against Ollama with the full
    # prompt. (A character-level prefix split used to sit here and rewrite
    # `request.prompt` down to the unmatched tail -- sending an EMPTY prompt on
    # an exact repeat. See node/core/completion_cache.py.)
    if request.stream:
        try:
            generator = ollama_client.generate_stream(request)

            async def stream_wrapper() -> AsyncGenerator[str, None]:
                # This used to build a `BackpressuredStreamRouter` whenever the node
                # had a live Zenoh session, and republish every generated chunk to
                # `public-intelligence/net/transport/stream/{id}`. Two defects, both
                # live, neither caught by any test because no test ever handed this
                # route a session that was not a mock:
                #
                # 1. PLAINTEXT LEAK. Completion text went onto the shared mesh in the
                #    clear, on a key any peer can subscribe to with a `**` wildcard,
                #    with no subscriber anywhere in this codebase. ROADMAP 2.7 spent
                #    a whole protocol change AES-256-GCM enveloping *telemetry* on
                #    that same mesh; the actual generated text was travelling beside
                #    it unprotected. The route also yielded `session_id: <id>` as the
                #    first line of the SSE body -- not a valid SSE field, and it
                #    handed the caller the topic to subscribe to.
                #
                # 2. DEADLOCK. `send_chunk` blocks once `sent - acked >= window_size`
                #    (default 4) and nothing in this repository ever sends an ACK, so
                #    any response longer than four chunks hung forever. Streaming was
                #    broken on precisely the deployment this project is built for: a
                #    node attached to the mesh.
                #
                # It was split-inference plumbing. Split inference is cut from v1 and
                # the gateway answers 501 for it (ROADMAP N1), so this served a
                # feature the product does not have. Removed rather than guarded --
                # dead code behind a disabled flag is how N1 happened.
                #
                # Pinned by tests/test_streaming_does_not_publish_to_the_mesh.py.
                #
                # A failure after the headers are sent cannot become an HTTP
                # error status -- the status line is already on the wire. With no
                # framing, uvicorn just closes the body and a truncated completion
                # is indistinguishable from a finished one: Ollama dying mid-answer
                # read as a normal end of stream. One explicit terminal frame makes
                # that machine-detectable.
                try:
                    async for chunk in generator:
                        yield chunk
                except OllamaError as e:
                    yield _sse_error_frame(502, str(e))
                except Exception as e:
                    yield _sse_error_frame(500, f"stream failed: {e}")

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

    # An exact repeat of a prompt this node has already answered is served
    # verbatim from the memo, without spending the host's GPU on it again.
    cached = completion_cache.lookup(request.prompt)
    if cached is not None:
        return InferenceResponse(model=request.model, response=cached)

    try:
        response = await ollama_client.generate(request)
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

    completion_cache.insert(request.prompt, response.response)
    return response


@router.get(
    "/models",
    response_model=list[ModelInfo],
    summary="List all hosted models",
    dependencies=[Depends(verify_node_auth)],
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
    response.status_code = status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ready" if is_ready else "degraded",
        "runtime": runtime_ready,
        "ollama": ollama_ready,
        "scheduler_registered": scheduler_registered,
        "wan_connected": wan_connected,
        "inference_ready": inference_ready,
        "last_heartbeat_at": (runtime.last_heartbeat_at if runtime is not None else None),
        "last_heartbeat_ok": (runtime.last_heartbeat_ok if runtime is not None else False),
        "last_heartbeat_error": (runtime.last_heartbeat_error if runtime is not None else None),
    }
