"""Inference API routes."""

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
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
    ollama_client: Annotated[OllamaClient, Depends(get_ollama_client)],
    radix_cache: Annotated[RadixTrieCache, Depends(get_radix_cache)],
) -> InferenceResponse | StreamingResponse:
    """Delegate inference to the Ollama client after prefix cache lookup."""
    original_prompt = request.prompt

    # Intercept prompt and lookup prefix
    prefix, suffix = await radix_cache.lookup_prefix(original_prompt)

    # Route only the remaining suffix data to the underlying backend serving model
    request.prompt = suffix

    if request.stream:
        try:
            generator = ollama_client.generate_stream(request)

            async def stream_wrapper() -> Any:
                try:
                    async for chunk in generator:
                        yield chunk
                finally:
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
