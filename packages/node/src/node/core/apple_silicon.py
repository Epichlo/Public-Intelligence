"""Apple Silicon Metal Unified Memory hardware profiler."""

import os
import subprocess
import sys
from typing import Any


def detect_apple_silicon_hardware() -> dict[str, Any]:
    """Detect Apple Silicon M1/M2/M3/M4 chip generation and Unified Memory.

    Returns:
        Dict containing is_apple_silicon, chip_family, unified_memory_gb, and metal_supported.
    """
    result: dict[str, Any] = {
        "is_apple_silicon": False,
        "chip_family": "Unknown",
        "unified_memory_gb": 0.0,
        "metal_supported": False,
    }

    if sys.platform != "darwin":
        return result

    try:
        proc = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True,
            text=True,
            check=False,
        )
        brand = proc.stdout.strip()
        if "Apple" in brand or os.uname().machine == "arm64":
            result["is_apple_silicon"] = True
            result["chip_family"] = brand if brand else "Apple Silicon ARM64"
            result["metal_supported"] = True

            mem_proc = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True,
                text=True,
                check=False,
            )
            if mem_proc.stdout.strip().isdigit():
                mem_bytes = int(mem_proc.stdout.strip())
                result["unified_memory_gb"] = round(mem_bytes / (1024**3), 2)
    except Exception:
        pass

    return result
