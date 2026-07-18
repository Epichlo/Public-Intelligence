"""Ollama client inference backend implementation."""

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from node.backends.base import InferenceBackend

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

    async def generate(
        self, model: str, prompt: str, options: dict[str, Any] | None = None
    ) -> str:
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
