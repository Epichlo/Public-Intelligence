"""Abstract base class contract for all model execution backends."""

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from typing import Any

from node.models.sharding import PipelineStage


class InferenceBackend(ABC):
    """Abstract interface class representing model inference engines."""

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize connection parameters and validate status.

        Raises:
            ConnectionError: If the target backend cannot be reached.
        """
        pass

    @abstractmethod
    async def generate(
        self, model: str, prompt: str, options: dict[str, Any] | None = None
    ) -> str:
        """Perform non-streaming text generation.

        Args:
            model: Name of the serving model.
            prompt: Plaintext user prompt to evaluate.
            options: Execution control arguments.

        Returns:
            The complete generated response string.
        """
        pass

    @abstractmethod
    async def generate_stream(
        self, model: str, prompt: str, options: dict[str, Any] | None = None
    ) -> AsyncGenerator[str, None]:
        """Perform token-by-token streaming text generation.

        Args:
            model: Name of the serving model.
            prompt: Plaintext user prompt to evaluate.
            options: Execution control arguments.

        Yields:
            Individual token strings.
        """
        yield ""

    @abstractmethod
    async def execute_pipeline_stage(
        self,
        stage: PipelineStage,
        input_tensors: Any | None = None,
        options: dict[str, Any] | None = None,
    ) -> Any:
        """Execute a single pipeline stage for model layer sharding.

        Args:
            stage: Pipeline stage specification containing layer range and metadata.
            input_tensors: Tensors or activations passed from previous stage.
            options: Execution control arguments.

        Returns:
            Processed stage tensor output or model payload.
        """
        pass
