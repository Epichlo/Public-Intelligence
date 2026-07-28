"""Scheduler-side inference request and result models."""

from pydantic import BaseModel, Field


class InferenceRequest(BaseModel):
    """Request forwarded to a selected Node."""

    model: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    stream: bool = False


class InferenceResponse(BaseModel):
    """Result returned by a Node inference API."""

    model: str
    response: str
