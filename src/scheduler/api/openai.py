"""OpenAI-compatible REST API Gateway router."""

import asyncio
import json
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import suppress
from typing import TYPE_CHECKING, Annotated, Any

if TYPE_CHECKING:
    from scheduler.registry.node_registry import NodeRegistry

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from scheduler.api.ingress import verify_jwt
from scheduler.core.boundary_engine import LocalBoundaryEngine
from scheduler.core.config import get_settings
from scheduler.core.transport import SharedMemoryIPC, get_tensor_topic
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
from scheduler.models.pipeline import LayerRange, PipelineStage, StageType, TensorPayload

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

    # 2. Split Inference Execution Path Guard
    is_split_req = (
        req_data.split_inference
        or request.headers.get("x-split-inference", "").lower() == "true"
        or getattr(get_settings(), "enable_split_inference", False)
    )

    if is_split_req:
        task_id = f"chatcmpl-split-{uuid.uuid4().hex[:12]}"
        task_data = {
            "task_id": task_id,
            "model_id": req_data.model,
            "model": req_data.model,
            "total_layers": 32,
            "requirements": {"model_name": req_data.model},
        }
        scheduling_engine = getattr(request.app.state, "scheduling_engine", None)

        if scheduling_engine is not None:
            try:
                stages = await scheduling_engine.schedule_split_inference_pipeline(
                    task_data, total_layers=32
                )
            except ValueError as e:
                logger.warning("openai_split_scheduling_failed", error=str(e))
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=(
                        f"No suitable compute nodes available for split inference model "
                        f"'{req_data.model}': {e}"
                    ),
                ) from e
        else:
            stages = [
                PipelineStage(
                    stage_index=0,
                    total_stages=3,
                    layer_range=LayerRange(start_layer=0, end_layer=0),
                    node_id="client_local",
                    model_id=req_data.model,
                    is_local_boundary=True,
                    stage_type=StageType.CLIENT_EMBEDDING,
                    is_split_inference=True,
                ),
                PipelineStage(
                    stage_index=1,
                    total_stages=3,
                    layer_range=LayerRange(start_layer=1, end_layer=31),
                    node_id="remote_node_1",
                    model_id=req_data.model,
                    is_local_boundary=False,
                    stage_type=StageType.REMOTE_HIDDEN,
                    is_split_inference=True,
                ),
                PipelineStage(
                    stage_index=2,
                    total_stages=3,
                    layer_range=LayerRange(start_layer=32, end_layer=32),
                    node_id="client_local",
                    model_id=req_data.model,
                    is_local_boundary=True,
                    stage_type=StageType.CLIENT_LM_HEAD,
                    is_split_inference=True,
                ),
            ]

        local_boundary = LocalBoundaryEngine(model_id=req_data.model)
        prompt_text = messages_to_prompt(req_data.messages)

        # Tokenize and compute local Layer 0 embeddings H_0
        h0_payload = local_boundary.embed_prompt(prompt_text, task_id=task_id)

        # Transmit activation vectors through intermediate remote host stages
        remote_stages = [s for s in stages if not s.is_local_boundary]
        stream_router = getattr(request.app.state, "stream_router", None)
        zenoh_session = getattr(request.app.state, "zenoh_session", None)
        timeout = float(getattr(get_settings(), "split_inference_timeout_seconds", 5.0))

        curr_payload = h0_payload
        for r_stage in remote_stages:
            resp_topic = get_tensor_topic(task_id, r_stage.stage_index + 1)

            if stream_router is not None and zenoh_session is not None:
                await stream_router.send_tensor_payload(curr_payload)

                loop = asyncio.get_running_loop()
                fut: asyncio.Future[TensorPayload] = loop.create_future()

                def _on_remote_activation(
                    sample: Any,
                    fut: asyncio.Future[TensorPayload] = fut,
                    loop: asyncio.AbstractEventLoop = loop,
                ) -> None:
                    try:
                        if hasattr(sample.payload, "to_bytes"):
                            raw_bytes = sample.payload.to_bytes()
                        elif isinstance(sample.payload, bytes):
                            raw_bytes = sample.payload
                        elif isinstance(sample.payload, str):
                            raw_bytes = sample.payload.encode("utf-8")
                        else:
                            raw_bytes = bytes(sample.payload)

                        if raw_bytes.startswith(b"shm://"):
                            shm_name = raw_bytes[6:].decode("utf-8", errors="ignore")
                            raw_bytes = SharedMemoryIPC.read_data(shm_name)
                            SharedMemoryIPC.cleanup(shm_name)

                        recv_payload = TensorPayload.from_framed_bytes(raw_bytes)
                        if not fut.done():
                            loop.call_soon_threadsafe(fut.set_result, recv_payload)
                    except Exception as exc:
                        if not fut.done():
                            loop.call_soon_threadsafe(fut.set_exception, exc)

                sub = zenoh_session.declare_subscriber(resp_topic, _on_remote_activation)
                try:
                    returned_payload = await asyncio.wait_for(fut, timeout=timeout)
                except TimeoutError as err:
                    logger.error(
                        "remote_split_stage_timeout",
                        task_id=task_id,
                        stage_index=r_stage.stage_index,
                    )
                    raise HTTPException(
                        status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                        detail=(
                            f"Gateway Timeout: Remote split stage {r_stage.stage_index} timed out "
                            f"after {timeout}s waiting for topic {resp_topic}"
                        ),
                    ) from err
                finally:
                    if hasattr(sub, "undeclare"):
                        with suppress(Exception):
                            sub.undeclare()

                try:
                    returned_payload.validate_split_activation_boundary()
                except ValueError as val_err:
                    logger.error(
                        "remote_split_stage_validation_failed",
                        task_id=task_id,
                        stage_index=r_stage.stage_index,
                        error=str(val_err),
                    )
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=(
                            f"Bad Gateway: Remote split stage {r_stage.stage_index} returned "
                            f"invalid activation payload: {val_err}"
                        ),
                    ) from val_err

                curr_payload = returned_payload
            else:
                if stream_router is not None:
                    await stream_router.send_tensor_payload(curr_payload)

                curr_payload = TensorPayload(
                    task_id=task_id,
                    stage_index=r_stage.stage_index,
                    target_stage_index=r_stage.stage_index + 1,
                    is_split_inference=True,
                    tensor_type="activation",
                    data=curr_payload.data,
                    shape=curr_payload.shape,
                    dtype=curr_payload.dtype,
                    sequence_id=curr_payload.sequence_id,
                )
                curr_payload.validate_split_activation_boundary()

        # Compute local Layer N LM Head unembedding and sampling
        _token_id, token_text = local_boundary.unembed_logits(
            curr_payload, temperature=req_data.temperature or 1.0
        )

        if not req_data.stream:
            prompt_tokens = estimate_tokens(prompt_text)
            completion_tokens = estimate_tokens(token_text)
            return ChatCompletionResponse(
                id=task_id,
                object="chat.completion",
                created=int(time.time()),
                model=req_data.model,
                choices=[
                    ChatCompletionResponseChoice(
                        index=0,
                        message=ChatMessage(role="assistant", content=token_text),
                        finish_reason="stop",
                    )
                ],
                usage=CompletionUsage(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=prompt_tokens + completion_tokens,
                ),
            )

        # Handle SSE streaming for split inference
        async def split_sse_generator() -> AsyncGenerator[str, None]:
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

            content_chunk = ChatCompletionChunk(
                id=task_id,
                object="chat.completion.chunk",
                created=int(time.time()),
                model=req_data.model,
                choices=[
                    ChatCompletionChunkChoice(
                        index=0,
                        delta=ChatCompletionChunkDelta(content=token_text),
                        finish_reason=None,
                    )
                ],
            )
            yield f"data: {content_chunk.model_dump_json()}\n\n"

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

        return StreamingResponse(split_sse_generator(), media_type="text/event-stream")

    # 3. Select Target Node via Scheduling Engine or NodeRegistry
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
