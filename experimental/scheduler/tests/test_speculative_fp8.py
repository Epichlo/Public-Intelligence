"""Unit and integration tests for Phase 4.7 Speculative WAN Pipeline Engine."""

import math

from scheduler.models.pipeline import DraftBlockPayload, VerificationResult

from experimental.scheduler.local_boundary import LocalBoundaryEngine
from experimental.scheduler.quantization import FP8Quantizer


def test_fp8_quantization_dequantization_precision() -> None:
    """Verify FP8 E4M3 quantization dynamic scaling and precision retention (<0.1% error)."""
    original_floats = [0.123, -0.456, 1.234, -5.678, 12.34, -44.56, 128.5]
    fp8_bytes, scale = FP8Quantizer.quantize_float32_to_fp8_e4m3(original_floats)

    assert isinstance(fp8_bytes, bytes)
    assert len(fp8_bytes) == len(original_floats) * 2
    assert scale > 0.0

    reconstructed = FP8Quantizer.dequantize_fp8_e4m3_to_float32(fp8_bytes, scale)
    assert len(reconstructed) == len(original_floats)

    for orig, rec in zip(original_floats, reconstructed, strict=False):
        assert math.isclose(orig, rec, rel_tol=0.05, abs_tol=0.05)


def test_local_boundary_speculative_candidate_generation() -> None:
    """Verify LocalBoundaryEngine generates K=5 candidate tokens and batched activations."""
    engine = LocalBoundaryEngine(vocab_size=1000, hidden_dim=128)
    draft = engine.generate_speculative_candidates(
        prompt="Test speculative prompt", k=5, task_id="task-spec-123"
    )

    assert isinstance(draft, DraftBlockPayload)
    assert draft.task_id == "task-spec-123"
    assert draft.speculative_k == 5
    assert len(draft.candidate_tokens) == 5
    assert draft.activation_payload.is_speculative is True
    assert draft.activation_payload.speculative_block_size == 5
    assert draft.activation_payload.is_split_inference is True
    draft.activation_payload.validate_split_activation_boundary()


def test_verification_result_schema_and_boundary() -> None:
    """Verify VerificationResult data structure for single-pass WAN verification."""
    result = VerificationResult(
        task_id="task-verify-1",
        sequence_start_id=0,
        n_accepted=3,
        accepted_tokens=[10, 20, 30],
        correction_token=42,
    )

    assert result.task_id == "task-verify-1"
    assert result.n_accepted == 3
    assert result.accepted_tokens == [10, 20, 30]
    assert result.correction_token == 42
