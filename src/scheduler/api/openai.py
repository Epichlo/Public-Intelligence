"""OpenAI-compatible REST API Gateway router."""

import json
import time
import uuid
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Annotated, Any

if TYPE_CHECKING:
    from scheduler.registry.node_registry import NodeRegistry

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from scheduler.api.ingress import verify_jwt
from scheduler.core.config import get_settings
from scheduler.models.openai import (
    ChatCompletionChunk,
    ChatCompletionChunkChoice,
    ChatCompletionChunkDelta,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionResponseChoice,
    ChatMessage,
    CompletionUsage,
    ModelListResponse,
    ModelObject,
)

logger = structlog.stdlib.get_logger()

router = APIRouter(tags=["openai"])


def messages_to_prompt(messages: list[ChatMessage]) -> str:
    """Convert OpenAI message list to a unified LLM prompt string."""
    parts: list[str] = []
    for msg in messages:
        role = msg.role
        content = msg.content
        if role == "system":
            parts.append(f"System: {content}")
        elif role == "user":
            parts.append(f"User: {content}")
        elif role == "assistant":
            parts.append(f"Assistant: {content}")
        else:
            parts.append(f"{role.capitalize()}: {content}")
    parts.append("Assistant:")
    return "\n\n".join(parts)


def estimate_tokens(text: str) -> int:
    """Estimate token count based on character length heuristic."""
    if not text:
        return 0
    return max(1, len(text) // 4)


@router.post(
    "/v1/chat/completions",
    response_model=None,
    summary="Create a chat completion (OpenAI API compatible)",
)
async def create_chat_completion(
    request: Request,
    req_data: ChatCompletionRequest,
    jwt_claims: Annotated[dict[str, Any], Depends(verify_jwt)],
) -> ChatCompletionResponse | StreamingResponse:
    """Create a chat completion for the provided prompt and parameters."""
    tenant_id = jwt_claims.get("tenant_id")
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid claims: Missing 'tenant_id' in token payload.",
        )

    # 1. Rate Limiting Guard
    rate_limiter = getattr(request.app.state, "rate_limiter", None)
    if rate_limiter is not None:
        allowed = await rate_limiter.acquire(tenant_id)
        if not allowed:
            logger.warning("openai_rate_limit_tripped", tenant_id=tenant_id)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Multi-tenant quota exhausted.",
            )

    # 2. Select Target Node via Scheduling Engine or NodeRegistry
    registry: NodeRegistry = request.app.state.registry
    scheduling_engine = getattr(request.app.state, "scheduling_engine", None)

    task_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    tx_hash = None
    target_node_id = None

    task_data = {
        "task_id": task_id,
        "requirements": {
            "model_name": req_data.model,
        },
    }

    if scheduling_engine is not None:
        try:
            tx_hash, target_node_id = await scheduling_engine.schedule_task(task_data)
        except ValueError as e:
            logger.warning("openai_scheduling_failed", error=str(e))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"No suitable compute node available for model '{req_data.model}': {e}",
            ) from e
    else:
        # Fallback to direct registry scan
        all_nodes = await registry.list()
        for n in all_nodes:
            if req_data.model in n.available_models:
                target_node_id = n.node_id
                break
        if target_node_id is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"No node available serving model '{req_data.model}'",
            )

    target_node = await registry.get(target_node_id)
    if target_node is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Target node '{target_node_id}' is no longer registered.",
        )

    # 3. Propose to Raft Consensus Engine if active
    consensus_engine = getattr(registry, "consensus_engine", None)
    if consensus_engine is not None and consensus_engine.is_active():
        try:
            await consensus_engine.propose(
                "allocate_task",
                {
                    "task_id": task_id,
                    "node_id": target_node_id,
                    "tx_hash": tx_hash or task_id,
                    "action": "chat_completion",
                    "data": {"model": req_data.model, "stream": req_data.stream},
                },
            )
        except Exception as e:
            logger.error("openai_consensus_proposal_failed", error=str(e))

    # 4. Proxy to Node /infer endpoint
    settings = get_settings()
    node_port = getattr(settings, "node_api_port", 8080)
    ip_host = target_node.ip_address
    if not ip_host.startswith("http://") and not ip_host.startswith("https://"):
        node_url = f"http://{ip_host}:{node_port}/infer"
    else:
        node_url = f"{ip_host}/infer"

    prompt_text = messages_to_prompt(req_data.messages)
    infer_payload = {
        "model": req_data.model,
        "prompt": prompt_text,
        "stream": req_data.stream,
    }

    # Handle Non-Streaming (stream=False)
    if not req_data.stream:
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                resp = await client.post(node_url, json=infer_payload)
            except httpx.RequestError as e:
                logger.error("node_infer_request_failed", url=node_url, error=str(e))
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Failed to communicate with compute node: {e}",
                ) from e

            if resp.status_code != 200:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=f"Compute node error: {resp.text}",
                )

            data = resp.json()
            generated_text = data.get("response", "")

        prompt_tokens = estimate_tokens(prompt_text)
        completion_tokens = estimate_tokens(generated_text)

        return ChatCompletionResponse(
            id=task_id,
            object="chat.completion",
            created=int(time.time()),
            model=req_data.model,
            choices=[
                ChatCompletionResponseChoice(
                    index=0,
                    message=ChatMessage(role="assistant", content=generated_text),
                    finish_reason="stop",
                )
            ],
            usage=CompletionUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
        )

    # Handle Streaming (stream=True)
    async def sse_generator() -> AsyncGenerator[str, None]:
        # 1) Send initial role chunk
        role_chunk = ChatCompletionChunk(
            id=task_id,
            object="chat.completion.chunk",
            created=int(time.time()),
            model=req_data.model,
            choices=[
                ChatCompletionChunkChoice(
                    index=0,
                    delta=ChatCompletionChunkDelta(role="assistant", content=""),
                    finish_reason=None,
                )
            ],
        )
        yield f"data: {role_chunk.model_dump_json()}\n\n"

        # 2) Connect to Node and stream deltas
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                async with client.stream("POST", node_url, json=infer_payload) as response:
                    if response.status_code != 200:
                        error_text = await response.aread()
                        err_chunk = ChatCompletionChunk(
                            id=task_id,
                            object="chat.completion.chunk",
                            created=int(time.time()),
                            model=req_data.model,
                            choices=[
                                ChatCompletionChunkChoice(
                                    index=0,
                                    delta=ChatCompletionChunkDelta(
                                        content=(
                                            "\n[Error: "
                                            f"{error_text.decode('utf-8', errors='ignore')}]"
                                        )
                                    ),
                                    finish_reason="error",
                                )
                            ],
                        )
                        yield f"data: {err_chunk.model_dump_json()}\n\n"
                        yield "data: [DONE]\n\n"
                        return

                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        clean_line = line
                        if clean_line.startswith("data: "):
                            clean_line = clean_line[6:].strip()

                        # Skip session_id header line if present from transport
                        if clean_line.startswith("session_id:"):
                            continue

                        token_content = clean_line
                        try:
                            json_obj = json.loads(clean_line)
                            if isinstance(json_obj, dict):
                                parsed_val = json_obj.get(
                                    "response", json_obj.get("text", clean_line)
                                )
                                token_content = str(parsed_val) if parsed_val is not None else ""
                        except json.JSONDecodeError:
                            pass

                        chunk_obj = ChatCompletionChunk(
                            id=task_id,
                            object="chat.completion.chunk",
                            created=int(time.time()),
                            model=req_data.model,
                            choices=[
                                ChatCompletionChunkChoice(
                                    index=0,
                                    delta=ChatCompletionChunkDelta(content=token_content),
                                    finish_reason=None,
                                )
                            ],
                        )
                        yield f"data: {chunk_obj.model_dump_json()}\n\n"
            except Exception as e:
                logger.error("openai_stream_error", error=str(e))
                err_chunk = ChatCompletionChunk(
                    id=task_id,
                    object="chat.completion.chunk",
                    created=int(time.time()),
                    model=req_data.model,
                    choices=[
                        ChatCompletionChunkChoice(
                            index=0,
                            delta=ChatCompletionChunkDelta(content=f"\n[Stream Error: {e}]"),
                            finish_reason="error",
                        )
                    ],
                )
                yield f"data: {err_chunk.model_dump_json()}\n\n"
                yield "data: [DONE]\n\n"
                return

        # 3) Final stop chunk
        stop_chunk = ChatCompletionChunk(
            id=task_id,
            object="chat.completion.chunk",
            created=int(time.time()),
            model=req_data.model,
            choices=[
                ChatCompletionChunkChoice(
                    index=0,
                    delta=ChatCompletionChunkDelta(),
                    finish_reason="stop",
                )
            ],
        )
        yield f"data: {stop_chunk.model_dump_json()}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(sse_generator(), media_type="text/event-stream")


@router.get(
    "/v1/models",
    response_model=ModelListResponse,
    summary="List available models",
)
async def list_models(request: Request) -> ModelListResponse:
    """List all available models registered across active nodes."""
    registry: NodeRegistry = request.app.state.registry
    nodes = await registry.list()

    models_set: set[str] = set()
    for n in nodes:
        models_set.update(n.available_models)

    model_objects = [
        ModelObject(id=model_id, created=1700000000, owned_by="public-intelligence")
        for model_id in sorted(models_set)
    ]

    return ModelListResponse(object="list", data=model_objects)


@router.get(
    "/v1/models/{model_id}",
    response_model=ModelObject,
    summary="Retrieve model details",
)
async def get_model(request: Request, model_id: str) -> ModelObject:
    """Retrieve details for a specific model ID."""
    registry: NodeRegistry = request.app.state.registry
    nodes = await registry.list()

    found = any(model_id in n.available_models for n in nodes)
    if not found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model '{model_id}' not found among active nodes.",
        )

    return ModelObject(id=model_id, created=1700000000, owned_by="public-intelligence")
