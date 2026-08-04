"""End-to-end split inference pipeline integration test suite.

Verifies full 3-tier split-inference pipeline execution across:
Local Layer 0 Embedding -> Remote Hidden Layers 1..N-1 -> Local Layer N LM Head.
"""

import pytest

from node.backends.mock import EchoBackend
from node.core.local_boundary import LocalBoundaryEngine
from node.models.sharding import LayerRange, PipelineStage, TensorPayload


@pytest.fixture
def local_boundary_engine() -> LocalBoundaryEngine:
    """Fixture providing local boundary engine for Layer 0 & Layer N."""
    return LocalBoundaryEngine(model_id="llama3-8b", vocab_size=1000, hidden_dim=128, seed=42)


@pytest.fixture
def mock_backend() -> EchoBackend:
    """Fixture providing remote hidden transformer backend runner."""
    return EchoBackend()


@pytest.mark.anyio
async def test_full_3_tier_split_inference_pipeline_execution(
    local_boundary_engine: LocalBoundaryEngine,
    mock_backend: EchoBackend,
) -> None:
    """Verify 3-tier split inference: Local Embedding -> Remote -> Local LM Head."""
    prompt = "Public Intelligence decentralized split inference pipeline"
    task_id = "task_e2e_3tier_001"

    # Tier 1: Local Layer 0 Embedding (Client Boundary)
    h0_payload = local_boundary_engine.embed_prompt(
        prompt=prompt, task_id=task_id, target_stage_index=1
    )

    assert h0_payload.stage_index == 0
    assert h0_payload.target_stage_index == 1
    assert h0_payload.is_split_inference is True
    assert h0_payload.tensor_type == "activation"
    assert len(h0_payload.data) > 0

    # Tier 2: Remote Hidden Layers 1..N-1 (Untrusted Compute Nodes)
    remote_stage_1 = PipelineStage(
        stage_index=1,
        total_stages=3,
        layer_range=LayerRange(start_layer=1, end_layer=15),
        node_id="remote-compute-node-1",
        model_id="llama3-8b",
        is_split_inference=True,
        stage_type="compute",
    )
    remote_stage_2 = PipelineStage(
        stage_index=2,
        total_stages=3,
        layer_range=LayerRange(start_layer=16, end_layer=30),
        node_id="remote-compute-node-2",
        model_id="llama3-8b",
        is_split_inference=True,
        stage_type="compute",
    )

    # Process through Remote Stage 1 (Node 1)
    h1_payload = await mock_backend.execute_split_stage(remote_stage_1, h0_payload)
    assert h1_payload.stage_index == 1
    assert h1_payload.target_stage_index == 2
    assert h1_payload.is_split_inference is True

    # Process through Remote Stage 2 (Node 2)
    h2_payload = await mock_backend.execute_split_stage(remote_stage_2, h1_payload)
    assert h2_payload.stage_index == 2
    assert h2_payload.is_split_inference is True

    # Tier 3: Local Layer N LM Head (Client Boundary Sampler)
    token_id, token_text = local_boundary_engine.unembed_logits(h2_payload, temperature=0.0)

    assert isinstance(token_id, int)
    assert 0 <= token_id < 1000
    assert isinstance(token_text, str)
    assert len(token_text) > 0


@pytest.mark.anyio
async def test_split_inference_pipeline_binary_framing_transport(
    local_boundary_engine: LocalBoundaryEngine,
    mock_backend: EchoBackend,
) -> None:
    """Verify 3-tier pipeline execution with binary frame serialization across tiers."""
    prompt = "Binary framed transport test prompt"
    task_id = "task_framed_pipeline_001"

    # Tier 1: Local Layer 0 Embedding
    h0_payload = local_boundary_engine.embed_prompt(
        prompt=prompt, task_id=task_id, target_stage_index=1
    )

    # Network Transport Tier 1 -> Tier 2 (Binary Framing)
    framed_h0 = h0_payload.to_framed_bytes()
    restored_h0 = TensorPayload.from_framed_bytes(framed_h0)

    # Tier 2: Remote Stage Execution
    remote_stage = PipelineStage(
        stage_index=1,
        total_stages=2,
        layer_range=LayerRange(start_layer=1, end_layer=30),
        node_id="remote-node-framed",
        model_id="llama3-8b",
        stage_type="compute",
        is_split_inference=True,
    )
    h1_payload = await mock_backend.execute_split_stage(remote_stage, restored_h0)

    # Network Transport Tier 2 -> Tier 3 (Binary Framing)
    framed_h1 = h1_payload.to_framed_bytes()
    restored_h1 = TensorPayload.from_framed_bytes(framed_h1)

    # Tier 3: Local Layer N LM Head Sampling
    token_id, token_text = local_boundary_engine.unembed_logits(restored_h1, temperature=0.7)

    assert isinstance(token_id, int)
    assert 0 <= token_id < 1000
    assert isinstance(token_text, str)


@pytest.mark.anyio
async def test_split_inference_pipeline_autoregressive_generation_loop(
    local_boundary_engine: LocalBoundaryEngine,
    mock_backend: EchoBackend,
) -> None:
    """Verify multi-token autoregressive generation loop across split pipeline."""
    initial_prompt = "Autoregressive split generation"
    generated_tokens: list[str] = []

    remote_stage = PipelineStage(
        stage_index=1,
        total_stages=2,
        layer_range=LayerRange(start_layer=1, end_layer=30),
        node_id="remote-node-loop",
        model_id="llama3-8b",
        stage_type="compute",
        is_split_inference=True,
    )

    # Run 5 generation steps
    curr_prompt = initial_prompt
    for step in range(5):
        task_id = f"task_loop_step_{step}"

        # 1. Local Layer 0 Embedding
        h0 = local_boundary_engine.embed_prompt(curr_prompt, task_id=task_id, target_stage_index=1)

        # 2. Remote Hidden Transformer Stage
        h1 = await mock_backend.execute_split_stage(remote_stage, h0)

        # 3. Local Layer N LM Head Sampler
        _token_id, token_text = local_boundary_engine.unembed_logits(h1, temperature=0.0)

        generated_tokens.append(token_text)
        curr_prompt += f" {token_text}"

    assert len(generated_tokens) == 5
    assert all(isinstance(tok, str) for tok in generated_tokens)
    assert len(local_boundary_engine._local_token_history) >= 5
