"""Empirical Challenger test suite for backend split stage execution.

Verifies EchoBackend and OllamaBackend behavior on split inference activation payloads.
"""

from typing import Any

import pytest

from node.backends.mock import EchoBackend
from node.backends.ollama import OllamaBackend
from node.models.sharding import LayerRange, PipelineStage, TensorPayload


@pytest.fixture
def sample_stage() -> PipelineStage:
    """Fixture providing a standard remote compute pipeline stage."""
    return PipelineStage(
        stage_index=1,
        total_stages=3,
        layer_range=LayerRange(start_layer=1, end_layer=30),
        node_id="host_node_1",
        model_id="mock-model",
        is_local_boundary=False,
        stage_type="compute",
        is_split_inference=True,
    )


@pytest.fixture
def valid_float_activation_payload() -> TensorPayload:
    """Fixture providing a valid intermediate float activation payload."""
    data = [0.1 * (i % 10) for i in range(512)]
    return TensorPayload(
        task_id="task_test_123",
        stage_index=0,
        target_stage_index=1,
        is_split_inference=True,
        tensor_type="intermediate_activation",
        data=data,
        shape=[1, 4, 128],
        dtype="float32",
        sequence_id=0,
    )


@pytest.fixture
def non_split_payload() -> TensorPayload:
    """Fixture providing a TensorPayload without split inference flag."""
    return TensorPayload(
        task_id="task_test_456",
        stage_index=0,
        target_stage_index=1,
        is_split_inference=False,
        tensor_type="full_prompt",
        data=b"Raw text prompt that should be rejected in split stage",
        shape=[],
        dtype="string",
    )


# ============================================================================
# 1. EchoBackend Tests
# ============================================================================


@pytest.mark.anyio
async def test_echo_backend_execute_split_stage_valid_float_payload(
    sample_stage: PipelineStage, valid_float_activation_payload: TensorPayload
) -> None:
    """Verify EchoBackend returns transformed float activation payload."""
    backend = EchoBackend()
    await backend.initialize()

    execute_fn: Any = getattr(backend, "execute_split_stage", None)
    if execute_fn is None:
        raise AttributeError("'EchoBackend' object has no attribute 'execute_split_stage'")

    result = await execute_fn(sample_stage, valid_float_activation_payload)

    assert hasattr(result, "is_split_inference"), "Result must be a TensorPayload"
    assert result.is_split_inference is True, "Output payload must retain is_split_inference=True"
    assert result.shape == valid_float_activation_payload.shape, (
        f"Expected shape {valid_float_activation_payload.shape}, got {result.shape}"
    )
    assert result.dtype == valid_float_activation_payload.dtype, (
        f"Expected dtype {valid_float_activation_payload.dtype}, got {result.dtype}"
    )
    assert result.stage_index == sample_stage.stage_index
    assert isinstance(result.data, (list, bytes))
    if isinstance(result.data, list):
        assert len(result.data) == len(valid_float_activation_payload.data), (
            "Float vector dimension count must match input payload"
        )


@pytest.mark.anyio
async def test_echo_backend_execute_split_stage_rejects_non_split_request(
    sample_stage: PipelineStage, non_split_payload: TensorPayload
) -> None:
    """Verify EchoBackend.execute_split_stage rejects non-split requests cleanly."""
    backend = EchoBackend()
    await backend.initialize()

    execute_fn: Any = getattr(backend, "execute_split_stage", None)
    if execute_fn is None:
        raise AttributeError("'EchoBackend' object has no attribute 'execute_split_stage'")

    with pytest.raises(ValueError) as exc_info:
        await execute_fn(sample_stage, non_split_payload)
    err = str(exc_info.value).lower()
    assert "split" in err or "reject" in err


@pytest.mark.anyio
async def test_echo_backend_execute_split_stage_rejects_invalid_payload_type(
    sample_stage: PipelineStage,
) -> None:
    """Verify EchoBackend rejects invalid non-TensorPayload inputs cleanly."""
    backend = EchoBackend()
    await backend.initialize()

    execute_fn: Any = getattr(backend, "execute_split_stage", None)
    if execute_fn is None:
        raise AttributeError("'EchoBackend' object has no attribute 'execute_split_stage'")

    with pytest.raises((ValueError, TypeError)) as exc_info:
        await execute_fn(sample_stage, "not_a_tensor_payload")
    assert exc_info.value is not None


@pytest.mark.anyio
async def test_echo_backend_execute_split_stage_rejects_corrupt_or_empty_data(
    sample_stage: PipelineStage,
) -> None:
    """Verify EchoBackend rejects payload with shape mismatch or empty data."""
    backend = EchoBackend()
    await backend.initialize()

    execute_fn: Any = getattr(backend, "execute_split_stage", None)
    if execute_fn is None:
        raise AttributeError("'EchoBackend' object has no attribute 'execute_split_stage'")

    corrupt_payload = TensorPayload(
        task_id="task_corrupt",
        stage_index=0,
        target_stage_index=1,
        is_split_inference=True,
        tensor_type="intermediate_activation",
        data=[],  # Empty data despite non-empty shape
        shape=[1, 4, 128],
        dtype="float32",
    )

    with pytest.raises((ValueError, TypeError)):
        await execute_fn(sample_stage, corrupt_payload)


@pytest.mark.anyio
async def test_echo_backend_execute_split_stage_rejects_prompt_like_payloads(
    sample_stage: PipelineStage,
) -> None:
    """Verify split stages reject structured or text-like prompt payloads."""
    backend = EchoBackend()
    await backend.initialize()

    malicious_payloads = [
        TensorPayload(
            task_id="task_prompt_type",
            stage_index=0,
            target_stage_index=1,
            is_split_inference=True,
            tensor_type="full_prompt",
            data=[1.0, 2.0],
            shape=[1, 2],
            dtype="float32",
        ),
        TensorPayload(
            task_id="task_string_dtype",
            stage_index=0,
            target_stage_index=1,
            is_split_inference=True,
            tensor_type="activation",
            data=b"secret prompt text",
            shape=[1, 18],
            dtype="string",
        ),
        TensorPayload(
            task_id="task_structured_prompt",
            stage_index=0,
            target_stage_index=1,
            is_split_inference=True,
            tensor_type="activation",
            data={"prompt": "do not send this to remote nodes", "token_ids": [1, 2, 3]},
            shape=[1, 3],
            dtype="float32",
        ),
        TensorPayload(
            task_id="task_bad_shape",
            stage_index=0,
            target_stage_index=1,
            is_split_inference=True,
            tensor_type="activation",
            data=[1.0, 2.0],
            shape=[1, 3],
            dtype="float32",
        ),
    ]

    for payload in malicious_payloads:
        with pytest.raises(ValueError):
            await backend.execute_split_stage(sample_stage, payload)


# ============================================================================
# 2. OllamaBackend Tests
# ============================================================================


@pytest.mark.anyio
async def test_ollama_backend_execute_split_stage_valid_float_payload(
    sample_stage: PipelineStage, valid_float_activation_payload: TensorPayload
) -> None:
    """Verify OllamaBackend returns float activation with matching shape and dtype."""
    backend = OllamaBackend(base_url="http://localhost:11434")

    execute_fn: Any = getattr(backend, "execute_split_stage", None)
    if execute_fn is None:
        raise AttributeError("'OllamaBackend' object has no attribute 'execute_split_stage'")

    result = await execute_fn(sample_stage, valid_float_activation_payload)

    assert result.is_split_inference is True
    assert result.shape == valid_float_activation_payload.shape
    assert result.dtype == valid_float_activation_payload.dtype
    assert result.stage_index == sample_stage.stage_index


@pytest.mark.anyio
async def test_ollama_backend_execute_split_stage_rejects_non_split_request(
    sample_stage: PipelineStage, non_split_payload: TensorPayload
) -> None:
    """Verify OllamaBackend.execute_split_stage rejects non-split requests cleanly."""
    backend = OllamaBackend(base_url="http://localhost:11434")

    execute_fn: Any = getattr(backend, "execute_split_stage", None)
    if execute_fn is None:
        raise AttributeError("'OllamaBackend' object has no attribute 'execute_split_stage'")

    with pytest.raises(ValueError) as exc_info:
        await execute_fn(sample_stage, non_split_payload)
    err = str(exc_info.value).lower()
    assert "split" in err or "reject" in err


@pytest.mark.anyio
async def test_ollama_backend_execute_split_stage_rejects_invalid_payload_type(
    sample_stage: PipelineStage,
) -> None:
    """Verify OllamaBackend rejects invalid non-TensorPayload inputs cleanly."""
    backend = OllamaBackend(base_url="http://localhost:11434")

    execute_fn: Any = getattr(backend, "execute_split_stage", None)
    if execute_fn is None:
        raise AttributeError("'OllamaBackend' object has no attribute 'execute_split_stage'")

    with pytest.raises((ValueError, TypeError)):
        await execute_fn(sample_stage, None)
