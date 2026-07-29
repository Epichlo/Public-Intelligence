"""Dynamic per-tensor FP8 E4M3 quantization and dequantization engine."""

import struct


class FP8Quantizer:
    """FP8 E4M3 quantization helper class for tensor activation compression."""

    E4M3_MAX: float = 448.0
    E4M3_MIN: float = 0.015625

    @classmethod
    def quantize_float32_to_fp8_e4m3(cls, tensor: list[float]) -> tuple[bytes, float]:
        """Quantizes float32 activation array to FP8 byte representation and returns scale factor.

        Args:
            tensor: List of float32 values.

        Returns:
            Tuple of (quantized_bytes, dynamic_scale_factor).
        """
        if not tensor:
            return b"", 1.0

        max_abs = max(abs(x) for x in tensor)
        scale = cls.E4M3_MAX / (max_abs + 1e-8) if max_abs > 0.0 else 1.0

        scaled_floats = [min(max(x * scale, -cls.E4M3_MAX), cls.E4M3_MAX) for x in tensor]
        packed_bytes = struct.pack(f">{len(scaled_floats)}e", *scaled_floats)
        return packed_bytes, scale

    @classmethod
    def dequantize_fp8_e4m3_to_float32(cls, fp8_bytes: bytes, scale: float) -> list[float]:
        """Dequantizes FP8 byte representation back to float32 values.

        Args:
            fp8_bytes: Quantized bytes buffer.
            scale: Scale factor used during quantization.

        Returns:
            List of dequantized float32 values.
        """
        if not fp8_bytes or len(fp8_bytes) % 2 != 0:
            return []

        num_floats = len(fp8_bytes) // 2
        unpacked_half = struct.unpack(f">{num_floats}e", fp8_bytes)
        inv_scale = 1.0 / scale if scale > 0.0 else 1.0
        return [float(x * inv_scale) for x in unpacked_half]
