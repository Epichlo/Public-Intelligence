"""Telemetry collector scraping CPU, RAM, and GPU stats from host system."""

import asyncio
import shutil
import subprocess
from typing import Any

import psutil


class TelemetryCollector:
    """Asynchronous telemetry collector for system hardware statistics."""

    async def collect(self) -> dict[str, Any]:
        """Collect current system resource metrics (CPU, RAM, GPU/VRAM).

        Returns:
            A dictionary containing structured telemetry metrics.
        """
        # 1. Collect CPU Metrics
        cpu_percent = psutil.cpu_percent(interval=None)
        cpu_count = psutil.cpu_count(logical=True) or 1

        # 2. Collect RAM Metrics
        mem = psutil.virtual_memory()
        ram_total_bytes = mem.total
        ram_available_bytes = mem.available
        ram_used_bytes = mem.used
        ram_percent = mem.percent

        # 3. Collect GPU Metrics (with fallback for non-NVIDIA systems)
        gpu_info = await self._collect_gpu_metrics()

        return {
            "cpu_utilization": float(cpu_percent),
            "cpu_cores": int(cpu_count),
            "ram_total_bytes": int(ram_total_bytes),
            "ram_available_bytes": int(ram_available_bytes),
            "ram_used_bytes": int(ram_used_bytes),
            "ram_utilization_pct": float(ram_percent),
            "gpu_name": gpu_info["name"],
            "gpu_utilization": float(gpu_info["utilization"]),
            "vram_total_bytes": int(gpu_info["vram_total_bytes"]),
            "vram_available_bytes": int(gpu_info["vram_available_bytes"]),
            "vram_used_bytes": int(gpu_info["vram_used_bytes"]),
        }

    async def _collect_gpu_metrics(self) -> dict[str, Any]:
        """Attempt to query NVIDIA GPU metrics via nvidia-smi.

        Falls back gracefully if nvidia-smi is unavailable.
        """
        default_gpu = {
            "name": "N/A",
            "utilization": 0.0,
            "vram_total_bytes": 0,
            "vram_available_bytes": 0,
            "vram_used_bytes": 0,
        }

        nvidia_smi_path = shutil.which("nvidia-smi")
        if not nvidia_smi_path:
            return default_gpu

        try:
            # Run nvidia-smi asynchronously to avoid event loop blocking
            process = await asyncio.create_subprocess_exec(
                nvidia_smi_path,
                "--query-gpu=name,utilization.gpu,memory.total,memory.free,memory.used",
                "--format=csv,noheader,nounits",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, _ = await process.communicate()
            if process.returncode != 0 or not stdout:
                return default_gpu

            line = stdout.decode("utf-8").strip().split("\n")[0]
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 5:
                name = parts[0]
                gpu_util = float(parts[1])
                # Convert MiB from output directly to Bytes
                vram_total = int(parts[2]) * 1024 * 1024
                vram_free = int(parts[3]) * 1024 * 1024
                vram_used = int(parts[4]) * 1024 * 1024

                return {
                    "name": name,
                    "utilization": gpu_util,
                    "vram_total_bytes": vram_total,
                    "vram_available_bytes": vram_free,
                    "vram_used_bytes": vram_used,
                }
        except Exception:
            # Fail silently and return fallback default dictionary
            pass

        return default_gpu
