"""Inference backends package initialization."""

from node.backends.base import InferenceBackend
from node.backends.mock import EchoBackend
from node.backends.ollama import OllamaBackend

__all__ = ["InferenceBackend", "OllamaBackend", "EchoBackend"]
