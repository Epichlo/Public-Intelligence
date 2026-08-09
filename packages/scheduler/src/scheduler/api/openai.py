"""OpenAI-compatible REST API Gateway router."""

import time
import uuid
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Annotated, Any

if TYPE_CHECKING:
    from scheduler.models.node import Node
    from scheduler.registry.node_registry import NodeRegistry

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from scheduler.api.auth import verify_auth_token
from scheduler.api.ingress import verify_jwt
from scheduler.api.nodes import get_mesh_client
from scheduler.core.config import get_settings
from scheduler.core.credit_ledger import CreditLedger
from scheduler.core.metering import UsageMeter, UsageRecord
from scheduler.core.node_dispatch import (
    NodeDispatchError,
    infer_once,
    open_inference_stream,
)
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

    # 2. Split inference is NOT IMPLEMENTED, and says so.
    #
    # This used to run the request through `LocalBoundaryEngine` -- seeded
    # `random.gauss` matrices over a toy vocabulary -- and return the result as a
    # normal 200 in the OpenAI response shape. Asking "What is the capital of
    # France?" with `x-split-inference: true` returned `content: 'token_556'`, which
    # every OpenAI-compatible client presents to a user as the model's answer.
    #
    # 501 is exactly the condition: the server understands the request and has no
    # implementation. A 400 would blame the caller for asking a reasonable question;
    # silently serving a non-split completion would tell them, in effect, that they
    # got what they asked for.
    #
    # The ~250-line execution block was DELETED rather than left behind this guard.
    # Dead code behind a disabled flag is how this happened: something written to be
    # finished later that stayed wired to the request path. Re-enabling split
    # inference now means writing it.
    # See specs/stop-returning-fabricated-completions.md.
    if (
        req_data.split_inference
        or request.headers.get("x-split-inference", "").lower() == "true"
        or getattr(get_settings(), "enable_split_inference", False)
    ):
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=(
                "Split inference is not implemented. It is cut from v1 (see ROADMAP.md); "
                "the previous implementation returned simulated tokens. Retry without "
                "`split_inference` / `x-split-inference` for a single-node completion."
            ),
        )

    # 3. Select Target Node via Scheduling Engine or NodeRegistry
    registry: NodeRegistry = request.app.state.registry
    scheduling_engine = getattr(request.app.state, "scheduling_engine", None)

    task_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    target_node_id = None
    # Started before matchmaking, so the recorded duration is what the REQUESTER
    # waited, not just what the node spent generating. A host reading their
    # dashboard should see the cost of the whole round trip their machine was in.
    started_at = time.time()

    task_data = {
        "task_id": task_id,
        "requirements": {
            "model_name": req_data.model,
        },
    }

    if scheduling_engine is not None:
        try:
            _tx_hash, target_node_id = await scheduling_engine.schedule_task(task_data)
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

    # The Raft proposal block that sat here is gone (ROADMAP C2). It proposed
    # through an engine whose only inbound path was an unauthenticated wildcard
    # Zenoh subscriber, and its failure branch swallowed every exception -- so a
    # broken consensus plane was invisible from here anyway.
    # 4. Dispatch to the node. Over the Zenoh mesh when it has been seen there -- the only
    # transport that reaches a node behind NAT, since `ip_address` is 127.0.0.1 for every
    # installer-provisioned node -- and by dialling its HTTP /infer otherwise. Transport
    # selection and credentials both live in scheduler/core/node_dispatch.py, shared with
    # schedule.py so the two proxy paths cannot drift apart.
    settings = get_settings()
    mesh_client = get_mesh_client(request)
    prompt_text = messages_to_prompt(req_data.messages)

    # Handle Non-Streaming (stream=False)
    if not req_data.stream:
        try:
            result = await infer_once(
                registry=registry,
                settings=settings,
                mesh_client=mesh_client,
                node_id=target_node_id,
                ip_address=target_node.ip_address,
                model=req_data.model,
                prompt=prompt_text,
            )
        except NodeDispatchError as e:
            # Metered as a FAILURE rather than not metered at all. "Which node keeps
            # failing" is the question this table has to be able to answer, and it is
            # the cheapest input D1's canary work can build on. No credit accrues --
            # `_meter` only credits when `succeeded`.
            #
            # This was missed on the first pass: the record model documented
            # `succeeded=False` while the only path that could produce one raised
            # before reaching the meter, so the flag was unreachable. A mutation that
            # removed the `and succeeded` guard survived the test suite, which is how
            # it was found.
            await _meter(
                request,
                request_id=task_id,
                tenant_id=tenant_id,
                node=target_node,
                model=req_data.model,
                prompt_tokens=estimate_tokens(prompt_text),
                completion_tokens=0,
                started_at=started_at,
                succeeded=False,
            )
            raise HTTPException(status_code=e.status, detail=e.detail) from e

        generated_text = result["response"]

        prompt_tokens = estimate_tokens(prompt_text)
        completion_tokens = estimate_tokens(generated_text)

        await _meter(
            request,
            request_id=task_id,
            tenant_id=tenant_id,
            node=target_node,
            model=req_data.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            started_at=started_at,
        )

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
    #
    # The transport is chosen here rather than inside the generator, while nothing has been
    # sent to the requester yet. That is the only moment at which falling back from the mesh
    # to HTTP is still possible, and it lets the node's own error -- a model it has not
    # pulled, say -- come back as a real status code instead of an error chunk buried in a
    # 200 response.
    try:
        token_stream = await open_inference_stream(
            registry=registry,
            settings=settings,
            mesh_client=mesh_client,
            node_id=target_node_id,
            ip_address=target_node.ip_address,
            model=req_data.model,
            prompt=prompt_text,
        )
    except NodeDispatchError as e:
        await _meter(
            request,
            request_id=task_id,
            tenant_id=tenant_id,
            node=target_node,
            model=req_data.model,
            prompt_tokens=estimate_tokens(prompt_text),
            completion_tokens=0,
            started_at=started_at,
            succeeded=False,
        )
        raise HTTPException(status_code=e.status, detail=e.detail) from e

    # Written by `sse_generator`, read by `metered_sse` after it finishes.
    #
    # `sse_generator` handles NodeDispatchError itself -- it emits an error chunk and
    # returns NORMALLY, because by then the response headers are long gone and there
    # is no status code left to set. That means the wrapper cannot tell success from
    # failure by watching for an exception: it sees a clean finish either way. This
    # dict is how the generator reports what really happened.
    #
    # Getting this wrong credited a node for a request that failed, which is the
    # precise incentive docs/decisions/D1-execution-integrity.md exists to avoid
    # creating. Pinned by
    # test_a_node_dying_mid_stream_is_recorded_as_a_FAILURE_and_credits_nobody.
    stream_outcome: dict[str, Any] = {"generated_chars": 0, "failed": False}

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

        # 2) Relay tokens from whichever transport was chosen above. Both hand back plain
        # token strings, so no SSE or JSON unwrapping happens here any more -- that moved
        # into node_dispatch alongside the HTTP client that produces the framing.
        try:
            async for token_content in token_stream:
                # The generated text, not the frame. The wrapper used to measure the
                # length of the serialised `data: {...}` envelopes, which counts JSON
                # punctuation, the model name and the request id once per token.
                stream_outcome["generated_chars"] += len(token_content)
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
        except NodeDispatchError as e:
            # Failed after the stream had opened. Too late for a status code, and too late
            # to switch transports, so the requester is told inside the stream.
            logger.error("openai_stream_node_error", error=e.detail, status=e.status)
            stream_outcome["failed"] = True
            err_chunk = ChatCompletionChunk(
                id=task_id,
                object="chat.completion.chunk",
                created=int(time.time()),
                model=req_data.model,
                choices=[
                    ChatCompletionChunkChoice(
                        index=0,
                        delta=ChatCompletionChunkDelta(content=f"\n[Error: {e.detail}]"),
                        finish_reason="error",
                    )
                ],
            )
            yield f"data: {err_chunk.model_dump_json()}\n\n"
            yield "data: [DONE]\n\n"
            return
        except Exception as e:
            logger.error("openai_stream_error", error=str(e))
            stream_outcome["failed"] = True
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

    async def metered_sse() -> AsyncGenerator[str, None]:
        """Wrap the stream so usage is recorded however it ends.

        Streaming is the path where metering is easy to get wrong. The response has
        already started, so there is no return statement to hang the accounting on,
        and there are two different kinds of ending to tell apart:

        * **The generator raises.** A client that disconnects half way through does
          this. `finally` catches it, and the record says the request did not
          succeed -- the node spent real time either way.
        * **The generator returns cleanly having failed.** `sse_generator` handles
          `NodeDispatchError` itself, emits an error chunk and returns, because by
          then there is no status code left to set. From out here that is
          indistinguishable from success, which is why `stream_outcome` exists.
          Reading only the exception credited a node for a failed request.
        """
        raised = False
        try:
            async for chunk in sse_generator():
                yield chunk
        except BaseException:
            # Includes GeneratorExit and CancelledError -- an abandoned connection
            # is the common case here, not an exceptional one.
            raised = True
            raise
        finally:
            await _meter(
                request,
                request_id=task_id,
                tenant_id=tenant_id,
                node=target_node,
                model=req_data.model,
                prompt_tokens=estimate_tokens(prompt_text),
                # Counted from the generated text the generator actually emitted,
                # not from the length of the SSE frames wrapping it.
                completion_tokens=(int(stream_outcome["generated_chars"]) // 4),
                started_at=started_at,
                succeeded=not raised and not stream_outcome["failed"],
            )

    return StreamingResponse(metered_sse(), media_type="text/event-stream")


# Authenticated as of ROADMAP C10. These were public on a 2.6 judgement -- "a
# marketplace should let a developer see what is servable before obtaining a
# credential" -- and that premise no longer exists. D1 made this an invite-only
# trusted-host network and D8 made it a self-hosted control plane for hardware you
# already own, so there is no anonymous developer shopping around: anyone who should
# see the catalogue already holds a credential from the operator.
#
# What stays true is the other half of the 2.6 reasoning -- this discloses model
# NAMES only, never which node has what. That is why it was a close call then and is
# not one now: the benefit went away and the disclosure did not.
async def _meter(
    request: Request,
    *,
    request_id: str,
    tenant_id: str,
    node: Node,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    started_at: float,
    succeeded: bool = True,
) -> None:
    """Record what a request consumed, and credit the node that served it.

    ROADMAP 3.2 and 3.3 in one place, because splitting them would let the ledger
    and the usage table disagree about what happened. The ledger was defined and
    unit-tested since long before this and had **no caller in the running app** --
    hosts earned nothing, and `CreditLedger`'s own docstring said so.

    Deliberately non-fatal. A metering failure must not turn a completion the
    requester already received into an error: the tokens are theirs either way, and
    the honest failure mode for an accounting system is a gap in the record, not a
    lost response. The gap is logged at ERROR so it is visible rather than silent.

    **Credits are an accounting unit, not a currency**
    (docs/decisions/D2-economics.md). Nothing here is redeemable and there is no
    payout path -- that is a decision, not an unfinished feature.
    """
    meter: UsageMeter | None = getattr(request.app.state, "usage_meter", None)
    ledger: CreditLedger | None = getattr(request.app.state, "ledger", None)
    duration = max(0.0, time.time() - started_at)

    try:
        if meter is not None:
            await meter.record(
                UsageRecord(
                    request_id=request_id,
                    tenant_id=tenant_id,
                    node_id=node.node_id,
                    model=model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    duration_seconds=duration,
                    succeeded=succeeded,
                )
            )
        # Only successful work accrues. Crediting a failed request would pay a node
        # for returning an error, which is precisely the incentive
        # docs/decisions/D1-execution-integrity.md exists to avoid creating.
        if ledger is not None and succeeded:
            await ledger.record_host_contribution(
                node_id=node.node_id,
                vram_gb=node.gpu.vram_total_gb,
                duration_seconds=duration,
            )
    except Exception:
        logger.exception("metering_failed", request_id=request_id, node_id=node.node_id)


@router.get(
    "/v1/models",
    response_model=ModelListResponse,
    summary="List available models",
    dependencies=[Depends(verify_auth_token)],
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
    dependencies=[Depends(verify_auth_token)],
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
