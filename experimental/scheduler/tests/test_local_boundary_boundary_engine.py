"""Unit tests for LocalBoundaryEngine and the split-inference tensor boundary.

QUARANTINED (ROADMAP C2). These cover `local_boundary.py` and `boundary_engine.py`,
which are cut from v1 and now live in `experimental/`. They were extracted from
`packages/scheduler/tests/test_openai_split_inference_challenger.py`, which mixed
them with gateway tests that DO cover shipping behaviour -- those stayed behind.

They do not run in the gate. See experimental/README.md for why that is the point.
"""

import pytest
from scheduler.models.pipeline import TensorPayload

from experimental.scheduler.boundary_engine import LocalBoundaryEngine as GatewayBoundaryEngine
from experimental.scheduler.local_boundary import LocalBoundaryEngine

# -----------------------------------------------------------------------------
# 1. Local Boundary Engine Unit & Integration Verification
# -----------------------------------------------------------------------------


def test_local_boundary_embed_prompt_split_inference_payload() -> None:
    """Verify embed_prompt creates a valid TensorPayload with split-inference flag."""
    boundary = LocalBoundaryEngine(vocab_size=1000, hidden_dim=128)
    prompt = "Test prompt for split inference embedding"
    payload = boundary.embed_prompt(prompt=prompt, task_id="task-m3-test", target_stage_index=1)

    assert isinstance(payload, TensorPayload)
    assert payload.is_split_inference is True
    assert payload.stage_index == 0
    assert payload.target_stage_index == 1
    assert payload.dtype == "float32"
    assert payload.shape[0] == 1
    assert payload.shape[2] == 128
    assert payload.shape[1] > 0

    # Ensure zero raw prompt text leakage in serialized payload metadata
    payload_repr = str(payload)
    assert prompt not in payload_repr
    assert "prompt" not in payload_repr.lower() or "activation" in payload_repr.lower()


def test_boundary_engine_module_reexports_the_canonical_engine() -> None:
    """Renamed: this never tested the gateway, and now the gateway has no link to it.

    It was `test_gateway_boundary_import_uses_canonical_local_boundary`, which
    implied `api/openai.py` resolves to this class. It does not -- ROADMAP N1
    removed that wiring, because reaching `LocalBoundaryEngine` from a request meant
    returning simulated tokens to a caller as a normal 200. All this checks is that
    `core/boundary_engine` re-exports `core/local_boundary`. Both modules are
    slated for quarantine under ROADMAP C2.
    """
    assert GatewayBoundaryEngine is LocalBoundaryEngine


def test_tensor_payload_split_boundary_rejects_prompt_like_payloads() -> None:
    """Verify split payload validation rejects prompt-like data across the boundary."""
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
            data={"messages": [{"role": "user", "content": "private"}], "token_ids": [1]},
            shape=[1, 1],
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
            payload.validate_split_activation_boundary()


def test_local_boundary_unembed_logits_sampling() -> None:
    """Verify unembed_logits performs LM Head projection and samples token deterministically."""
    boundary = LocalBoundaryEngine(vocab_size=1000, hidden_dim=128)

    # Mock activation vector H_(N-1) payload
    h_data = [0.1 * (i % 10) for i in range(128)]
    activation_payload = TensorPayload(
        task_id="task-m3-unembed",
        stage_index=2,
        target_stage_index=3,
        is_split_inference=True,
        tensor_type="activation",
        data=h_data,
        shape=[1, 1, 128],
        dtype="float32",
    )

    # Temperature 0.0 (greedy)
    tid1, text1 = boundary.unembed_logits(activation_payload, temperature=0.0)
    tid2, text2 = boundary.unembed_logits(activation_payload, temperature=0.0)

    assert isinstance(tid1, int)
    assert isinstance(text1, str)
    assert 0 <= tid1 < 1000
    assert tid1 == tid2
    assert text1 == text2
