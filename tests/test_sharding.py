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
        data=[1.0, 2.0, 3.0],
        shape=[1, 3],
        dtype="float32",
        shm_name="shm_test_123",
    )
    assert payload.task_id == "task-123"
    assert payload.stage_index == 0
    assert payload.data == [1.0, 2.0, 3.0]
    assert payload.shape == [1, 3]
    assert payload.dtype == "float32"
    assert payload.shm_name == "shm_test_123"
