"""Unit and integration tests for Phase 4.7 Speculative WAN Pipeline Engine."""

import math

from node.core.local_boundary import LocalBoundaryEngine
from node.core.quantization import FP8Quantizer
from node.models.sharding import DraftBlockPayload, VerificationResult


def test_node_fp8_quantization_dequantization_precision() -> None:
    """Verify Node FP8 E4M3 quantization dynamic scaling and precision retention."""
    original_floats = [0.05, -0.15, 2.5, -10.0, 50.0, -200.0]
    fp8_bytes, scale = FP8Quantizer.quantize_float32_to_fp8_e4m3(original_floats)

    assert isinstance(fp8_bytes, bytes)
    assert len(fp8_bytes) == len(original_floats) * 2
    assert scale > 0.0

    reconstructed = FP8Quantizer.dequantize_fp8_e4m3_to_float32(fp8_bytes, scale)
    assert len(reconstructed) == len(original_floats)

    for orig, rec in zip(original_floats, reconstructed, strict=False):
        assert math.isclose(orig, rec, rel_tol=0.05, abs_tol=0.05)


def test_node_speculative_candidate_generation() -> None:
    """Verify Node LocalBoundaryEngine generates candidate blocks for speculative execution."""
    engine = LocalBoundaryEngine(vocab_size=1000, hidden_dim=128)
    draft = engine.generate_speculative_candidates(
        prompt="Node speculative candidate test", k=5, task_id="node-spec-456"
    )

    assert isinstance(draft, DraftBlockPayload)
    assert draft.task_id == "node-spec-456"
    assert draft.speculative_k == 5
    assert len(draft.candidate_tokens) == 5
    assert draft.activation_payload.is_speculative is True
    assert draft.activation_payload.is_split_inference is True
    draft.activation_payload.validate_split_activation_boundary()


def test_node_verification_result_schema() -> None:
    """Verify Node VerificationResult model initialization."""
    res = VerificationResult(
        task_id="node-ver-1",
        sequence_start_id=0,
        n_accepted=4,
        accepted_tokens=[1, 2, 3, 4],
        correction_token=5,
    )
    assert res.task_id == "node-ver-1"
    assert res.n_accepted == 4
    assert res.accepted_tokens == [1, 2, 3, 4]
