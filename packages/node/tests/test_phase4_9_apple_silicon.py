"""Unit and integration tests for Node Phase 4.9 Apple Silicon hardware profiler."""

from node.core.apple_silicon import detect_apple_silicon_hardware


def test_detect_apple_silicon_hardware() -> None:
    """Verify Apple Silicon hardware detection helper keys and structure."""
    info = detect_apple_silicon_hardware()

    assert isinstance(info, dict)
    assert "is_apple_silicon" in info
    assert "chip_family" in info
    assert "unified_memory_gb" in info
    assert "metal_supported" in info
