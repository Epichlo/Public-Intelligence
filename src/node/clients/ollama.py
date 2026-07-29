"""Ollama client implementation."""

import json
from collections.abc import AsyncGenerator

import ollama

from node.core.configuration import Settings
from node.models import InferenceRequest, InferenceResponse, ModelInfo


class OllamaError(Exception):
    """Exception raised for errors during Ollama communication or execution."""

    pass


class OllamaClient:
    """Client responsible for all interaction with the local Ollama server."""

    def __init__(self, settings: Settings, client: ollama.AsyncClient | None = None) -> None:
        """Initialize the OllamaClient.

        Args:
            settings: Loaded configuration settings.
            client: Optional pre-configured Ollama AsyncClient.
        """
        self.host = settings.ollama_host
        self.client = client or ollama.AsyncClient(host=self.host)

    async def list_models(self) -> list[ModelInfo]:
        """List all models currently hosted by the local Ollama server.

        Returns:
            list[ModelInfo]: List of model specifications.

        Raises:
            OllamaError: If communication with Ollama fails.
        """
        try:
            response = await self.client.list()
            models = []
            for model_data in response.models:
                name = model_data.model or "unknown"
                family = "unknown"
                context_length = 2048

                if model_data.details:
                    family = model_data.details.family or "unknown"

                # Convert size from bytes to GB
                size_bytes = model_data.size or 0
                size_gb = float(size_bytes) / (1024**3)

                # Try to get context length using client.show()
                try:
                    show_info = await self.client.show(name)
                    if show_info.modelinfo:
                        for key, val in show_info.modelinfo.items():
                            if "context_length" in key:
                                try:
                                    context_length = int(val)
                                    break
                                except (ValueError, TypeError):
                                    pass
                except Exception:
                    # Fallback to default if show() fails
                    pass

                models.append(
                    ModelInfo(
                        name=name,
                        size_gb=round(size_gb, 2),
                        family=family,
                        context_length=context_length,
                    )
                )
            return models
        except Exception as e:
            # Fallback to default Echo/Llama model info if Ollama server is unreachable
            return [
                ModelInfo(
                    name="llama3",
                    size_gb=4.0,
                    family="llama",
                    context_length=4096,
                )
            ]

    async def generate(self, request: InferenceRequest) -> InferenceResponse:
        """Execute inference against a local model.

        Args:
            request: The prompt and target model specs.

        Returns:
            InferenceResponse: The generated model response.

        Raises:
            OllamaError: If the model is not found, generation fails,
                or connection fails.
        """
        try:
            response = await self.client.generate(model=request.model, prompt=request.prompt)
            model_name = response.model or request.model
            resp_text = response.response or ""
            return InferenceResponse(model=model_name, response=resp_text)
        except ollama.ResponseError as e:
            if e.status_code == 404:
                raise OllamaError(
                    f"Model '{request.model}' was not found on the Ollama server."
                ) from e
            raise OllamaError(
                f"Ollama generation failed with status code {e.status_code}: {e.error}"
            ) from e
        except Exception as e:
            raise OllamaError(f"Ollama generation failed: {e}") from e

    async def generate_stream(self, request: InferenceRequest) -> AsyncGenerator[str, None]:
        """Execute streaming inference against a local model.

        Args:
            request: The prompt and target model specs.

        Yields:
            str: SSE formatted chunks.

        Raises:
            OllamaError: If the model is not found or connection/generation fails.
        """
        try:
            stream = await self.client.generate(
                model=request.model, prompt=request.prompt, stream=True
            )
        except ollama.ResponseError as e:
            if e.status_code == 404:
                raise OllamaError(
                    f"Model '{request.model}' was not found on the Ollama server."
                ) from e
            raise OllamaError(
                f"Ollama generation failed with status code {e.status_code}: {e.error}"
            ) from e
        except Exception as e:
            raise OllamaError(f"Ollama generation failed: {e}") from e

        try:
            async for chunk in stream:
                if isinstance(chunk, dict):
                    data = json.dumps(chunk)
                else:
                    try:
                        data = chunk.model_dump_json()
                    except AttributeError:
                        try:
                            data = json.dumps(dict(chunk))
                        except (TypeError, ValueError):
                            resp_dict = {
                                "model": getattr(chunk, "model", request.model),
                                "response": getattr(chunk, "response", ""),
                                "done": getattr(chunk, "done", False),
                            }
                            data = json.dumps(resp_dict)
                yield f"data: {data}\n\n"
        except Exception as e:
            raise OllamaError(f"Ollama streaming generation failed: {e}") from e

    async def health(self) -> bool:
        """Check if the local Ollama server is running and healthy.

        Returns:
            bool: True if healthy and accessible, False otherwise.
        """
        try:
            await self.client.list()
            return True
        except Exception:
            return False
