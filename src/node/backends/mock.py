"""Deterministic mock echo inference backend."""

# ruff: noqa: ARG002

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

from node.backends.base import InferenceBackend


class EchoBackend(InferenceBackend):
    """Deterministic mock inference backend for testing. Mirrors user prompts."""

    async def initialize(self) -> None:
        """Mock initialization, always succeeds."""
        pass

    async def generate(
        self, model: str, prompt: str, options: dict[str, Any] | None = None
    ) -> str:
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
