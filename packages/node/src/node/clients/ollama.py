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
        # Resolved context lengths, keyed by model digest. `list()` is now called on
        # an interval rather than once at startup (see specs/truthful-model-catalogue.md),
        # and each entry it returns used to cost a follow-up `show()` -- an N+1 against
        # Ollama every refresh. The digest changes exactly when the model's content
        # does, so it is the correct key: a re-pull invalidates, a re-list does not.
        self._context_length_by_digest: dict[str, int] = {}

    async def _resolve_context_length(self, name: str, digest: str | None) -> int:
        """Return the model's context length, asking Ollama at most once per digest.

        Falls back to 2048 when `show()` fails or reports nothing usable. That
        fallback is deliberately *not* cached: it means "we do not know yet", and
        caching it would make one transient failure permanent for that digest.
        """
        if digest and digest in self._context_length_by_digest:
            return self._context_length_by_digest[digest]

        try:
            show_info = await self.client.show(name)
            if show_info.modelinfo:
                for key, val in show_info.modelinfo.items():
                    if "context_length" in key:
                        try:
                            context_length = int(val)
                        except (ValueError, TypeError):
                            continue
                        if digest:
                            self._context_length_by_digest[digest] = context_length
                        return context_length
        except Exception:
            # Fallback to default if show() fails
            pass

        return 2048

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

                if model_data.details:
                    family = model_data.details.family or "unknown"

                # Convert size from bytes to GB
                size_bytes = model_data.size or 0
                size_gb = float(size_bytes) / (1024**3)

                context_length = await self._resolve_context_length(
                    name, getattr(model_data, "digest", None)
                )

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
            raise OllamaError(f"Failed to list models: {e}") from e

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
