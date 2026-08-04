"""Deterministic mock echo inference backend."""

# ruff: noqa: ARG002

import asyncio
import struct
from collections.abc import AsyncGenerator
from typing import Any

from node.backends.base import InferenceBackend
from node.models.sharding import PipelineStage, TensorPayload


class EchoBackend(InferenceBackend):
    """Deterministic mock inference backend for testing. Mirrors user prompts."""

    async def initialize(self) -> None:
        """Mock initialization, always succeeds."""
        pass

    async def generate(self, model: str, prompt: str, options: dict[str, Any] | None = None) -> str:
        """Directly echo back the prompt in a formatted string.

        Args:
            model: Target model name.
            prompt: Input text prompt.
            options: Unused options.

        Returns:
            The echoed formatted prompt.
        """
        return f"Echo: {prompt}"

    async def generate_stream(
        self, model: str, prompt: str, options: dict[str, Any] | None = None
    ) -> AsyncGenerator[str, None]:
        """Directly yield chunks of the mirrored prompt for testing.

        Args:
            model: Target model name.
            prompt: Input text prompt.
            options: Unused options.

        Yields:
            Tokens of the echoed prompt.
        """
        response_text = f"Echo: {prompt}"
        tokens = response_text.split(" ")
        for i, token in enumerate(tokens):
            chunk = token if i == len(tokens) - 1 else token + " "
            yield chunk
            await asyncio.sleep(0.001)

    async def execute_pipeline_stage(
        self,
        stage: PipelineStage,
        input_tensors: Any | None = None,
        options: dict[str, Any] | None = None,
    ) -> Any:
        """Execute a single pipeline stage deterministically for testing.

        Args:
            stage: Target pipeline stage configuration.
            input_tensors: Input payload from previous stage.
            options: Execution control parameters.

        Returns:
            Mock output payload containing stage metadata and processed input.
        """
        return {
            "stage_index": stage.stage_index,
            "layer_range": (stage.layer_range.start_layer, stage.layer_range.end_layer),
            "output_tensors": (
                f"Mock output for stage {stage.stage_index} with input {input_tensors}"
            ),
        }

    async def execute_split_stage(
        self,
        stage: PipelineStage,
        input_payload: TensorPayload,
        options: dict[str, Any] | None = None,
    ) -> TensorPayload:
        """Execute intermediate transformer layers for split inference.

        Args:
            stage: Target pipeline stage configuration.
            input_payload: Incoming TensorPayload containing activation vectors.
            options: Execution control parameters.

        Returns:
            Transformed TensorPayload for next stage with is_split_inference=True.
        """
        if not isinstance(input_payload, TensorPayload):
            raise TypeError("input_payload must be an instance of TensorPayload")

        input_payload.validate_split_activation_boundary()

        delta = 0.01 * (stage.stage_index + 1)
        if isinstance(input_payload.data, list):
            if input_payload.data and isinstance(input_payload.data[0], list):
                transformed_data: Any = [
                    [float(x) + delta for x in row] if isinstance(row, list) else float(row) + delta
                    for row in input_payload.data
                ]
            else:
                transformed_data = [float(x) + delta for x in input_payload.data]
        elif isinstance(input_payload.data, bytes):
            num_floats = len(input_payload.data) // 4
            is_framed = input_payload.data.startswith(b"PITP")
            fmt = f">{num_floats}f" if is_framed else f"{num_floats}f"
            unpacked = struct.unpack(fmt, input_payload.data)
            transformed = [val + delta for val in unpacked]
            transformed_data = struct.pack(fmt, *transformed)
        else:
            transformed_data = input_payload.data

        target_idx = stage.stage_index + 1

        return TensorPayload(
            task_id=input_payload.task_id,
            stage_index=stage.stage_index,
            target_stage_index=target_idx,
            is_split_inference=True,
            tensor_type="activation",
            data=transformed_data,
            shape=input_payload.shape,
            dtype=input_payload.dtype,
            sequence_id=input_payload.sequence_id,
            shm_name=input_payload.shm_name,
        )
