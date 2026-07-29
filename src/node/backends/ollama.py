"""Ollama client inference backend implementation."""

# ruff: noqa: ARG002

import json
import logging
import struct
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from node.backends.base import InferenceBackend
from node.models.sharding import PipelineStage, TensorPayload

logger = logging.getLogger(__name__)


class OllamaBackend(InferenceBackend):
    """Concrete implementation of InferenceBackend targeting a local Ollama instance."""

    def __init__(self, base_url: str = "http://localhost:11434") -> None:
        """Initialize the OllamaBackend.

        Args:
            base_url: Base HTTP endpoint of the local Ollama daemon.
        """
        self.base_url = base_url.rstrip("/")

    async def initialize(self) -> None:
        """Validate connection status with the local Ollama server."""
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(self.base_url)
                if response.status_code != 200:
                    raise ConnectionError(
                        f"Ollama server returned status code: {response.status_code}"
                    )
            except httpx.RequestError as e:
                raise ConnectionError(
                    f"Could not connect to Ollama server at {self.base_url}: {e}"
                ) from e

    async def generate(self, model: str, prompt: str, options: dict[str, Any] | None = None) -> str:
        """Generate complete text output for the given prompt.

        Uses non-streaming request.

        Args:
            model: Name of the target model.
            prompt: Input text prompt.
            options: Configuration options passed to Ollama.

        Returns:
            The fully generated output text response.
        """
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": options or {},
        }
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self.base_url}/api/generate", json=payload, timeout=60.0
                )
                response.raise_for_status()
                data = response.json()
                return str(data["response"])
            except (
                httpx.HTTPStatusError,
                httpx.RequestError,
                KeyError,
                json.JSONDecodeError,
            ) as e:
                raise RuntimeError(f"Ollama generation failed: {e}") from e

    async def generate_stream(
        self, model: str, prompt: str, options: dict[str, Any] | None = None
    ) -> AsyncGenerator[str, None]:
        """Stream generated text chunks iteratively using line-by-line JSON parsing.

        Args:
            model: Name of the target model.
            prompt: Input text prompt.
            options: Configuration options passed to Ollama.

        Yields:
            Text token chunks as they are emitted by Ollama.
        """
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": True,
            "options": options or {},
        }
        headers = {"Content-Type": "application/json"}

        # We construct the generator loop inside a context manager
        # to ensure the connection handles clean teardowns
        async with httpx.AsyncClient() as client:
            try:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/api/generate",
                    json=payload,
                    headers=headers,
                    timeout=60.0,
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            chunk = data.get("response", "")
                            if chunk:
                                yield chunk
                        except json.JSONDecodeError:
                            logger.warning(
                                "Failed to decode streaming line from Ollama: %s",
                                line,
                            )
            except (httpx.HTTPStatusError, httpx.RequestError) as e:
                raise RuntimeError(f"Ollama stream generation failed: {e}") from e

    async def execute_pipeline_stage(
        self,
        stage: PipelineStage,
        input_tensors: Any | None = None,
        options: dict[str, Any] | None = None,
    ) -> Any:
        """Execute a single pipeline stage targeting Ollama.

        Args:
            stage: Target pipeline stage configuration.
            input_tensors: Input payload or prompt text from previous stage.
            options: Execution control parameters.

        Returns:
            Generated text output for the stage.
        """
        model_opt = options.get("model") if options else None
        model: str = stage.model_id or (str(model_opt) if model_opt else "default")
        prompt = (
            f"Stage {stage.stage_index} "
            f"[Layers {stage.layer_range.start_layer}-{stage.layer_range.end_layer}]: "
            f"{input_tensors}"
        )
        return await self.generate(model=model, prompt=prompt, options=options)

    async def execute_split_stage(
        self,
        stage: PipelineStage,
        input_payload: TensorPayload,
        options: dict[str, Any] | None = None,
    ) -> TensorPayload:
        """Execute activation stage for split inference on Ollama backend.

        Args:
            stage: PipelineStage configuration.
            input_payload: Incoming activation TensorPayload.
            options: Execution options.

        Returns:
            TensorPayload with updated stage index and transformed activation vectors.
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
