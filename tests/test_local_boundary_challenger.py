"""Empirical stress and validation test suite for LocalBoundaryEngine.

Authored by CHALLENGER 1 for Milestone M2 of Phase 4.6.
Tests token embedding generation, local LM Head unembedding, and sampling.
"""

import random
import struct
from typing import Any

import pytest

from node.models.sharding import TensorPayload

# Attempt to import LocalBoundaryEngine from node.core.local_boundary
try:
    from node.core.local_boundary import LocalBoundaryEngine

    LOCAL_BOUNDARY_AVAILABLE = True
except ImportError:
    LOCAL_BOUNDARY_AVAILABLE = False


@pytest.fixture
def dummy_local_engine() -> Any:
    """Fixture to instantiate LocalBoundaryEngine if available."""
    if not LOCAL_BOUNDARY_AVAILABLE:
        pytest.fail("node.core.local_boundary.LocalBoundaryEngine missing")
    return LocalBoundaryEngine(vocab_size=1000, hidden_dim=128)


@pytest.mark.anyio
async def test_import_local_boundary_engine() -> None:
    """Verify LocalBoundaryEngine module and class exist and can be imported."""
    assert LOCAL_BOUNDARY_AVAILABLE, (
        "FAIL: node.core.local_boundary.LocalBoundaryEngine could not be imported."
    )


@pytest.mark.anyio
async def test_embed_prompt_shape_and_dtype() -> None:
    """Verify embed_prompt produces float32 activations."""
    if not LOCAL_BOUNDARY_AVAILABLE:
        pytest.fail("LocalBoundaryEngine missing")

    engine = LocalBoundaryEngine(vocab_size=1000, hidden_dim=128)
    prompt = "Hello world empirical challenge test"
    payload = engine.embed_prompt(prompt)

    assert isinstance(payload, TensorPayload)
    assert payload.is_split_inference is True
    assert payload.dtype == "float32"
    assert payload.stage_index == 0
    assert payload.tensor_type in ("activation", "intermediate_activation")
    assert len(payload.shape) == 3
    assert payload.shape[0] == 1
    assert payload.shape[2] == 128
    assert payload.shape[1] > 0

    # Data must be flat 1D list of floats equal to seq_len * hidden_dim
    assert isinstance(payload.data, list)
    expected_len = payload.shape[1] * payload.shape[2]
    assert len(payload.data) == expected_len


@pytest.mark.anyio
async def test_embed_prompt_zero_text_leakage() -> None:
    """Verify zero raw text or token IDs are exposed in the output TensorPayload."""
    if not LOCAL_BOUNDARY_AVAILABLE:
        pytest.fail("LocalBoundaryEngine missing")

    engine = LocalBoundaryEngine(vocab_size=1000, hidden_dim=128)
    secret_prompt = "CONFIDENTIAL_PASSPHRASE_12345_SECRET_PROMPT"
    payload = engine.embed_prompt(secret_prompt)

    # Check raw string representations of data and metadata
    payload_str = str(payload)
    assert secret_prompt not in payload_str
    assert "CONFIDENTIAL" not in payload_str
    assert payload.dtype == "float32"

    # Check data content does not contain raw string bytes or plain token IDs
    if isinstance(payload.data, bytes):
        assert secret_prompt.encode("utf-8") not in payload.data
    elif isinstance(payload.data, list):
        for item in payload.data:
            assert isinstance(item, float)


@pytest.mark.anyio
async def test_unembed_logits_temperature_sampling() -> None:
    """Verify LM Head unembedding computes logits & samples across temperatures."""
    if not LOCAL_BOUNDARY_AVAILABLE:
        pytest.fail("LocalBoundaryEngine missing")

    engine = LocalBoundaryEngine(vocab_size=1000, hidden_dim=128)

    seq_len = 5
    hidden_dim = 128
    activations = [random.uniform(-1.0, 1.0) for _ in range(seq_len * hidden_dim)]

    activation_payload = TensorPayload(
        task_id="task_m2_unembed_test",
        stage_index=2,
        target_stage_index=3,
        is_split_inference=True,
        tensor_type="activation",
        data=activations,
        shape=[1, seq_len, hidden_dim],
        dtype="float32",
    )

    # 1. Temperature = 0.0 (greedy / argmax) should be deterministic across calls
    t_id_1, t_text_1 = engine.unembed_logits(activation_payload, temperature=0.0)
    t_id_2, t_text_2 = engine.unembed_logits(activation_payload, temperature=0.0)

    assert isinstance(t_id_1, int)
    assert isinstance(t_text_1, str)
    assert 0 <= t_id_1 < 1000
    assert t_id_1 == t_id_2
    assert t_text_1 == t_text_2

    # 2. Test positive temperatures (0.7, 1.0, 2.0)
    for temp in [0.7, 1.0, 2.0]:
        tid, ttext = engine.unembed_logits(activation_payload, temperature=temp)
        assert isinstance(tid, int)
        assert isinstance(ttext, str)
        assert 0 <= tid < 1000


@pytest.mark.anyio
async def test_unembed_logits_bytes_payload() -> None:
    """Verify unembed_logits processes packed float bytes activation payloads."""
    if not LOCAL_BOUNDARY_AVAILABLE:
        pytest.fail("LocalBoundaryEngine missing")

    engine = LocalBoundaryEngine(vocab_size=1000, hidden_dim=128)

    hidden_dim = 128
    float_vector = [random.uniform(-1.0, 1.0) for _ in range(hidden_dim)]
    packed_bytes = struct.pack(f"{hidden_dim}f", *float_vector)

    payload = TensorPayload(
        task_id="task_bytes_unembed",
        stage_index=2,
        target_stage_index=3,
        is_split_inference=True,
        tensor_type="activation",
        data=packed_bytes,
        shape=[1, 1, hidden_dim],
        dtype="float32",
    )

    token_id, token_text = engine.unembed_logits(payload, temperature=1.0)
    assert isinstance(token_id, int)
    assert isinstance(token_text, str)
    assert 0 <= token_id < 1000


@pytest.mark.anyio
async def test_unembed_logits_rejects_non_split_payload_or_invalid_bytes() -> None:
    """Verify unembed_logits behavior when passed unaligned bytes."""
    if not LOCAL_BOUNDARY_AVAILABLE:
        pytest.fail("LocalBoundaryEngine missing")

    engine = LocalBoundaryEngine(vocab_size=1000, hidden_dim=128)

    non_split_payload = TensorPayload(
        task_id="task_non_split",
        stage_index=2,
        target_stage_index=3,
        is_split_inference=False,
        tensor_type="raw_text",
        data=b"Raw text prompt",
        shape=[],
        dtype="string",
    )

    with pytest.raises((ValueError, struct.error)):
        engine.unembed_logits(non_split_payload)
