"""Security audit test suite for split inference local boundary isolation.

Verifies remote nodes receive 0 raw prompt text, messages, or token IDs.
Validates payload structures across intermediate hidden transformer stages.
"""

import struct

import pytest
from node.backends.mock import EchoBackend
from node.models.sharding import LayerRange, PipelineStage, TensorPayload

from experimental.node.local_boundary import LocalBoundaryEngine


@pytest.fixture
def local_boundary_engine() -> LocalBoundaryEngine:
    """Fixture providing a configured LocalBoundaryEngine instance."""
    return LocalBoundaryEngine(vocab_size=1000, hidden_dim=128, seed=42)


@pytest.fixture
def mock_backend() -> EchoBackend:
    """Fixture providing an EchoBackend instance for remote pipeline execution."""
    return EchoBackend()


def test_split_inference_security_audit_payload_isolation(
    local_boundary_engine: LocalBoundaryEngine,
) -> None:
    """Verify raw prompt text is never exposed in TensorPayload for remote stages."""
    secret_prompt = "CONFIDENTIAL_TOP_SECRET_PROMPT_DATA_12345"
    payload = local_boundary_engine.embed_prompt(
        secret_prompt, task_id="sec_task_001", target_stage_index=1
    )

    payload_data = payload.model_dump()

    # Exact required security assertions
    assert "prompt" not in payload_data
    assert "messages" not in payload_data
    assert payload.is_split_inference is True
    assert payload.tensor_type == "activation"
    assert not isinstance(payload.data, str)
    assert all(isinstance(v, float) for v in payload.data)

    # Verification that sensitive text strings do not leak in tensor data representation
    data_str = str(payload.data)
    assert secret_prompt not in data_str
    assert "CONFIDENTIAL" not in data_str
    assert "SECRET" not in data_str


def test_split_inference_security_audit_bytes_tensor_payload(
    local_boundary_engine: LocalBoundaryEngine,
) -> None:
    """Verify float byte tensor payloads contain zero plaintext token ID strings."""
    prompt = "Public Intelligence Zero Leakage Security Audit"
    payload = local_boundary_engine.embed_prompt(
        prompt, task_id="sec_task_bytes_001", target_stage_index=1
    )

    # Convert activation data list to packed float bytes
    assert isinstance(payload.data, list)
    floats_list = payload.data
    packed_bytes = struct.pack(f">{len(floats_list)}f", *floats_list)

    bytes_payload = TensorPayload(
        task_id=payload.task_id,
        stage_index=payload.stage_index,
        target_stage_index=payload.target_stage_index,
        is_split_inference=payload.is_split_inference,
        tensor_type=payload.tensor_type,
        data=packed_bytes,
        shape=payload.shape,
        dtype=payload.dtype,
    )

    payload_data = bytes_payload.model_dump()

    # Exact required security assertions
    assert "prompt" not in payload_data
    assert "messages" not in payload_data
    assert bytes_payload.is_split_inference is True
    assert bytes_payload.tensor_type == "activation"
    assert not isinstance(bytes_payload.data, str)

    # Binary frame assertion
    framed_bytes = bytes_payload.to_framed_bytes()
    assert framed_bytes.startswith(b"PITP")
    assert prompt.encode("utf-8") not in framed_bytes


@pytest.mark.anyio
async def test_split_inference_security_audit_remote_stage_interception(
    local_boundary_engine: LocalBoundaryEngine,
    mock_backend: EchoBackend,
) -> None:
    """Intercept remote hidden stage payloads (Layers 1..N-1) and assert 0 leak."""
    secret_prompt = "CLASSIFIED_MESSAGES_PAYLOAD_USER_QUERY_88"
    h0_payload = local_boundary_engine.embed_prompt(
        secret_prompt, task_id="task_remote_intercept_001", target_stage_index=1
    )

    remote_stage_1 = PipelineStage(
        stage_index=1,
        total_stages=3,
        layer_range=LayerRange(start_layer=1, end_layer=15),
        node_id="remote-hidden-node-alpha",
        model_id="llama3-8b",
        is_split_inference=True,
        stage_type="compute",
    )

    # Simulate network transmission to remote hidden stage (Layer 1..N-1)
    h1_payload = await mock_backend.execute_split_stage(remote_stage_1, h0_payload)
    payload_data = h1_payload.model_dump()

    # Assert intercepted remote hidden stage payload maintains complete security boundary
    assert "prompt" not in payload_data
    assert "messages" not in payload_data
    assert h1_payload.is_split_inference is True
    assert h1_payload.tensor_type == "activation"
    assert not isinstance(h1_payload.data, str)
    assert all(isinstance(v, float) for v in h1_payload.data)

    # Output activation values remain purely floating point vector transformations
    assert len(h1_payload.data) == len(h0_payload.data)


def test_split_inference_security_audit_token_id_absence(
    local_boundary_engine: LocalBoundaryEngine,
) -> None:
    """Verify raw integer token IDs are not exposed in remote stage activation payloads."""
    prompt = "Top secret system prompt instructions"
    payload = local_boundary_engine.embed_prompt(
        prompt, task_id="sec_task_tokens_001", target_stage_index=1
    )

    assert isinstance(payload.data, list)

    # Payload data elements are float vectors, not raw integer token IDs
    assert all(isinstance(val, float) for val in payload.data)

    # Verify model_dump keys do not expose token history
    payload_dict = payload.model_dump()
    assert "tokens" not in payload_dict
    assert "token_ids" not in payload_dict
