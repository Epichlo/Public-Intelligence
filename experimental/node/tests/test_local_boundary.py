"""Unit tests for client/edge LocalBoundaryEngine."""

import struct

import pytest
from node.models.sharding import TensorPayload

from experimental.node.local_boundary import LocalBoundaryEngine


def test_local_boundary_engine_initialization() -> None:
    """Verify LocalBoundaryEngine initializes local weights and vocabulary cleanly."""
    engine = LocalBoundaryEngine(model_id="test-model", vocab_size=1000, hidden_dim=128)
    assert engine.model_id == "test-model"
    assert engine.vocab_size == 1000
    assert engine.hidden_dim == 128
    assert len(engine.embedding_matrix) == 1000
    assert len(engine.embedding_matrix[0]) == 128
    assert len(engine.lm_head_matrix) == 1000
    assert len(engine.lm_head_matrix[0]) == 128


def test_embed_prompt_generation() -> None:
    """Verify embed_prompt tokenizes and computes H_0 Layer 0 activations."""
    engine = LocalBoundaryEngine(vocab_size=500, hidden_dim=64)
    prompt = "Hello Public Intelligence split inference boundary"

    payload = engine.embed_prompt(prompt, task_id="task_embed_001", target_stage_index=1)

    assert isinstance(payload, TensorPayload)
    assert payload.task_id == "task_embed_001"
    assert payload.stage_index == 0
    assert payload.target_stage_index == 1
    assert payload.is_split_inference is True
    assert payload.tensor_type == "activation"
    assert payload.dtype == "float32"

    num_tokens = len(prompt.lower().strip().split())
    assert payload.shape == [1, num_tokens, 64]

    assert isinstance(payload.data, list)
    assert len(payload.data) == num_tokens * 64

    payload_dict = payload.model_dump()
    assert "prompt" not in payload_dict
    assert "messages" not in payload_dict
    payload_data_str = str(payload_dict["data"]).lower()
    for word in ["hello", "public", "intelligence", "boundary"]:
        assert word not in payload_data_str


def test_embed_prompt_empty_fallback() -> None:
    """Verify embed_prompt handles empty or whitespace prompt gracefully."""
    engine = LocalBoundaryEngine(vocab_size=500, hidden_dim=64)
    payload = engine.embed_prompt("   ")

    assert payload.stage_index == 0
    assert payload.is_split_inference is True
    assert payload.shape[0] == 1
    assert payload.shape[1] >= 1
    assert payload.shape[2] == 64


def test_unembed_logits_list_data() -> None:
    """Verify unembed_logits processes list activation data cleanly."""
    engine = LocalBoundaryEngine(vocab_size=500, hidden_dim=64, seed=123)
    activation_vec = [0.05 * (i % 10) for i in range(64)]

    payload = TensorPayload(
        task_id="task_unembed_001",
        stage_index=1,
        target_stage_index=2,
        is_split_inference=True,
        tensor_type="activation",
        data=activation_vec,
        shape=[1, 1, 64],
        dtype="float32",
    )

    token_id, token_text = engine.unembed_logits(payload, temperature=0.0)

    assert isinstance(token_id, int)
    assert 0 <= token_id < 500
    assert isinstance(token_text, str)
    assert len(token_text) > 0


def test_unembed_logits_bytes_data() -> None:
    """Verify unembed_logits processes bytes activation data cleanly."""
    engine = LocalBoundaryEngine(vocab_size=500, hidden_dim=64, seed=123)
    floats = [0.01 * i for i in range(64)]
    packed_bytes = struct.pack(f">{64}f", *floats)

    payload = TensorPayload(
        task_id="task_unembed_002",
        stage_index=1,
        target_stage_index=2,
        is_split_inference=True,
        tensor_type="activation",
        data=packed_bytes,
        shape=[1, 1, 64],
        dtype="float32",
    )

    token_id, token_text = engine.unembed_logits(payload, temperature=1.0)

    assert isinstance(token_id, int)
    assert 0 <= token_id < 500
    assert isinstance(token_text, str)


def test_unembed_logits_invalid_payload_raises() -> None:
    """Verify unembed_logits raises ValueError on corrupt activation payload data."""
    engine = LocalBoundaryEngine(vocab_size=500, hidden_dim=64)
    payload = TensorPayload(
        task_id="task_err",
        stage_index=1,
        target_stage_index=2,
        is_split_inference=True,
        tensor_type="activation",
        data=[],
        shape=[1, 1, 64],
        dtype="float32",
    )

    with pytest.raises(ValueError) as exc_info:
        engine.unembed_logits(payload)
    err_msg = str(exc_info.value).lower()
    assert "empty" in err_msg or "no floating point" in err_msg
