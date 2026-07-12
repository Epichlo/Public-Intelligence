"""Tests for domain models."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from node.models import (
    Heartbeat,
    InferenceRequest,
    InferenceResponse,
    ModelInfo,
    NodeInfo,
)

# =====================================================================
# ModelInfo Tests
# =====================================================================


def test_model_info_success() -> None:
    """Verify successful construction of ModelInfo."""
    model = ModelInfo(
        name="llama3-8b", size_gb=4.7, family="llama", context_length=8192
    )
    assert model.name == "llama3-8b"
    assert model.size_gb == 4.7
    assert model.family == "llama"
    assert model.context_length == 8192


def test_model_info_failures() -> None:
    """Verify validation failures for ModelInfo."""
    # Empty name
    with pytest.raises(ValidationError):
        ModelInfo(name=" ", size_gb=4.7, family="llama", context_length=8192)

    # Empty family
    with pytest.raises(ValidationError):
        ModelInfo(name="llama3-8b", size_gb=4.7, family="", context_length=8192)

    # Negative size
    with pytest.raises(ValidationError):
        ModelInfo(
            name="llama3-8b",
            size_gb=-0.1,
            family="llama",
            context_length=8192,
        )

    # Non-positive context length
    with pytest.raises(ValidationError):
        ModelInfo(name="llama3-8b", size_gb=4.7, family="llama", context_length=0)


# =====================================================================
# NodeInfo Tests
# =====================================================================


def test_node_info_success() -> None:
    """Verify successful construction of NodeInfo."""
    model_a = ModelInfo(
        name="llama3-8b", size_gb=4.7, family="llama", context_length=8192
    )
    node = NodeInfo(
        node_id="node-1",
        hostname="node.local",
        region="us-east",
        ip_address="192.168.1.50",
        cpu_cores=8,
        ram_total_gb=16.0,
        available_models=[model_a],
    )
    assert node.node_id == "node-1"
    assert node.hostname == "node.local"
    assert node.region == "us-east"
    assert node.ip_address == "192.168.1.50"
    assert node.cpu_cores == 8
    assert node.ram_total_gb == 16.0
    assert len(node.available_models) == 1
    assert node.available_models[0].name == "llama3-8b"


def test_node_info_failures() -> None:
    """Verify validation failures for NodeInfo."""
    # Empty fields
    with pytest.raises(ValidationError):
        NodeInfo(
            node_id="",
            hostname="node.local",
            region="us-east",
            ip_address="192.168.1.50",
            cpu_cores=8,
            ram_total_gb=16.0,
        )

    # Invalid IP address
    with pytest.raises(ValidationError):
        NodeInfo(
            node_id="node-1",
            hostname="node.local",
            region="us-east",
            ip_address="192.168.1.300",  # invalid octet
            cpu_cores=8,
            ram_total_gb=16.0,
        )

    # Non-positive CPU cores
    with pytest.raises(ValidationError):
        NodeInfo(
            node_id="node-1",
            hostname="node.local",
            region="us-east",
            ip_address="192.168.1.50",
            cpu_cores=0,
            ram_total_gb=16.0,
        )

    # Non-positive RAM
    with pytest.raises(ValidationError):
        NodeInfo(
            node_id="node-1",
            hostname="node.local",
            region="us-east",
            ip_address="192.168.1.50",
            cpu_cores=8,
            ram_total_gb=0.0,
        )


# =====================================================================
# Heartbeat Tests
# =====================================================================


def test_heartbeat_success() -> None:
    """Verify successful construction of Heartbeat."""
    now = datetime.now()
    hb = Heartbeat(
        node_id="node-1",
        timestamp=now,
        queue_length=2,
        cpu_utilization=45.5,
        ram_available_gb=8.2,
        gpu_utilization=90.0,
        vram_available_gb=4.5,
    )
    assert hb.node_id == "node-1"
    assert hb.timestamp == now
    assert hb.queue_length == 2
    assert hb.cpu_utilization == 45.5
    assert hb.ram_available_gb == 8.2
    assert hb.gpu_utilization == 90.0
    assert hb.vram_available_gb == 4.5


def test_heartbeat_failures() -> None:
    """Verify validation failures for Heartbeat."""
    now = datetime.now()

    # Empty node_id
    with pytest.raises(ValidationError):
        Heartbeat(
            node_id=" ",
            timestamp=now,
            queue_length=0,
            cpu_utilization=0.0,
            ram_available_gb=0.0,
            gpu_utilization=0.0,
            vram_available_gb=0.0,
        )

    # Negative queue length
    with pytest.raises(ValidationError):
        Heartbeat(
            node_id="node-1",
            timestamp=now,
            queue_length=-1,
            cpu_utilization=0.0,
            ram_available_gb=0.0,
            gpu_utilization=0.0,
            vram_available_gb=0.0,
        )

    # Out of range utilization (CPU > 100)
    with pytest.raises(ValidationError):
        Heartbeat(
            node_id="node-1",
            timestamp=now,
            queue_length=0,
            cpu_utilization=100.1,
            ram_available_gb=0.0,
            gpu_utilization=0.0,
            vram_available_gb=0.0,
        )

    # Negative memory (VRAM)
    with pytest.raises(ValidationError):
        Heartbeat(
            node_id="node-1",
            timestamp=now,
            queue_length=0,
            cpu_utilization=0.0,
            ram_available_gb=0.0,
            gpu_utilization=0.0,
            vram_available_gb=-0.5,
        )


# =====================================================================
# InferenceRequest / InferenceResponse Tests
# =====================================================================


def test_inference_request_success() -> None:
    """Verify successful construction of InferenceRequest."""
    req = InferenceRequest(model="llama3-8b", prompt="Hello world")
    assert req.model == "llama3-8b"
    assert req.prompt == "Hello world"


def test_inference_request_failures() -> None:
    """Verify validation failures for InferenceRequest."""
    # Empty model name
    with pytest.raises(ValidationError):
        InferenceRequest(model="", prompt="Hello")

    # Empty prompt
    with pytest.raises(ValidationError):
        InferenceRequest(model="llama3-8b", prompt="   ")


def test_inference_response_success() -> None:
    """Verify successful construction of InferenceResponse."""
    resp = InferenceResponse(model="llama3-8b", response="Hi there")
    assert resp.model == "llama3-8b"
    assert resp.response == "Hi there"


def test_inference_response_failures() -> None:
    """Verify validation failures for InferenceResponse."""
    # Empty model name
    with pytest.raises(ValidationError):
        InferenceResponse(model=" ", response="Hi")
