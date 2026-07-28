"""Tests for node pipeline sharding models."""

import pytest
from pydantic import ValidationError

from node.models import LayerRange, PipelineStage, TensorPayload


def test_layer_range_success() -> None:
    """Verify valid LayerRange construction and properties."""
    lr = LayerRange(start_layer=0, end_layer=15)
    assert lr.start_layer == 0
    assert lr.end_layer == 15
    assert lr.num_layers == 16

    single_layer = LayerRange(start_layer=5, end_layer=5)
    assert single_layer.num_layers == 1


def test_layer_range_validation_failure() -> None:
    """Verify LayerRange validation fails when start_layer > end_layer."""
    with pytest.raises(ValidationError):
        LayerRange(start_layer=15, end_layer=10)

    with pytest.raises(ValidationError):
        LayerRange(start_layer=-1, end_layer=5)


def test_pipeline_stage_success() -> None:
    """Verify valid PipelineStage construction and properties."""
    lr = LayerRange(start_layer=0, end_layer=15)
    stage0 = PipelineStage(
        stage_index=0,
        total_stages=2,
        layer_range=lr,
        node_id="node-1",
        model_id="llama3-70b",
    )

    assert stage0.stage_index == 0
    assert stage0.total_stages == 2
    assert stage0.is_first_stage is True
    assert stage0.is_last_stage is False
    assert stage0.num_layers == 16

    lr_last = LayerRange(start_layer=16, end_layer=31)
    stage1 = PipelineStage(
        stage_index=1,
        total_stages=2,
        layer_range=lr_last,
        node_id="node-2",
        model_id="llama3-70b",
    )

    assert stage1.is_first_stage is False
    assert stage1.is_last_stage is True
    assert stage1.num_layers == 16


def test_pipeline_stage_validation_failure() -> None:
    """Verify PipelineStage validation fails when stage_index >= total_stages."""
    lr = LayerRange(start_layer=0, end_layer=15)
    with pytest.raises(ValidationError):
        PipelineStage(
            stage_index=2,
            total_stages=2,
            layer_range=lr,
            node_id="node-1",
        )


def test_tensor_payload_success() -> None:
    """Verify TensorPayload construction and field access."""
    payload = TensorPayload(
        task_id="task-123",
        stage_index=0,
        target_stage_index=1,
        is_split_inference=True,
        tensor_type="intermediate_activation",
        data=[1.0, 2.0, 3.0],
        shape=[1, 3],
        dtype="float32",
        sequence_id=5,
        shm_name="shm_test_123",
    )
    assert payload.task_id == "task-123"
    assert payload.stage_index == 0
    assert payload.target_stage_index == 1
    assert payload.is_split_inference is True
    assert payload.tensor_type == "intermediate_activation"
    assert payload.data == [1.0, 2.0, 3.0]
    assert payload.shape == [1, 3]
    assert payload.dtype == "float32"
    assert payload.sequence_id == 5
    assert payload.shm_name == "shm_test_123"


def test_pipeline_stage_split_inference_extensions() -> None:
    """Verify PipelineStage split-inference boundary extensions."""
    lr = LayerRange(start_layer=0, end_layer=0)
    stage = PipelineStage(
        stage_index=0,
        total_stages=3,
        layer_range=lr,
        node_id="local-client",
        model_id="llama3-8b",
        is_local_boundary=True,
        stage_type="local_embedding",
        is_split_inference=True,
    )
    assert stage.is_local_boundary is True
    assert stage.stage_type == "local_embedding"
    assert stage.is_split_inference is True


def test_tensor_payload_binary_framing_raw_bytes() -> None:
    """Verify binary framing serialization and deserialization for raw bytes payload."""
    raw_data = b"\x00\x01\x02\x03\x04\x05\x06\x07"
    payload = TensorPayload(
        task_id="task-framing-1",
        stage_index=0,
        target_stage_index=1,
        is_split_inference=True,
        tensor_type="intermediate_activation",
        data=raw_data,
        shape=[1, 2, 4],
        dtype="float32",
        sequence_id=42,
    )

    framed = payload.to_framed_bytes()
    assert framed.startswith(b"PITP")

    restored = TensorPayload.from_framed_bytes(framed)
    assert restored.task_id == "task-framing-1"
    assert restored.stage_index == 0
    assert restored.target_stage_index == 1
    assert restored.is_split_inference is True
    assert restored.tensor_type == "intermediate_activation"
    assert restored.data == raw_data
    assert restored.shape == [1, 2, 4]
    assert restored.dtype == "float32"
    assert restored.sequence_id == 42


def test_tensor_payload_binary_framing_json_data() -> None:
    """Verify binary framing serialization and deserialization for JSON list payload."""
    data_list = [0.1, 0.2, 0.3, 0.4]
    payload = TensorPayload(
        task_id="task-framing-2",
        stage_index=1,
        target_stage_index=2,
        is_split_inference=False,
        data=data_list,
        shape=[1, 4],
        dtype="float32",
    )

    framed = payload.to_framed_bytes()
    assert framed.startswith(b"PITP")

    restored = TensorPayload.from_framed_bytes(framed)
    assert restored.task_id == "task-framing-2"
    assert restored.stage_index == 1
    assert restored.target_stage_index == 2
    assert restored.is_split_inference is False
    assert restored.data == data_list


def test_tensor_payload_fallback_json_deserialization() -> None:
    """Verify fallback JSON parsing when magic header is absent."""
    json_bytes = (
        b'{"task_id": "json-task", "stage_index": 0, '
        b'"target_stage_index": 1, "data": [1.0, 2.0]}'
    )
    restored = TensorPayload.from_framed_bytes(json_bytes)
    assert restored.task_id == "json-task"
    assert restored.stage_index == 0
    assert restored.target_stage_index == 1
    assert restored.data == [1.0, 2.0]
