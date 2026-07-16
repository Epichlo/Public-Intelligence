"""Inference API routes."""

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from node.clients import OllamaClient, OllamaError
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


@router.post(
    "/infer",
    response_model=InferenceResponse,
    summary="Execute inference against a local model",
)
async def infer(
    request: InferenceRequest,
    ollama_client: Annotated[OllamaClient, Depends(get_ollama_client)],
) -> InferenceResponse | StreamingResponse:
    """Delegate inference generation directly to the Ollama client."""
    if request.stream:
        try:
            generator = ollama_client.generate_stream(request)
            return StreamingResponse(generator, media_type="text/event-stream")
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
        return await ollama_client.generate(request)
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
