"""Pipeline scheduling models for model layer sharding."""

import json
from enum import Enum
from math import prod
from typing import Any, Self

from pydantic import BaseModel, Field, model_validator


class LayerRange(BaseModel):
    """Specifies a contiguous range of model layers assigned to a pipeline stage."""

    start_layer: int = Field(ge=0, description="Inclusive start layer index")
    end_layer: int = Field(ge=0, description="Inclusive end layer index")

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        """Validate that start_layer <= end_layer."""
        if self.start_layer > self.end_layer:
            raise ValueError("start_layer must be less than or equal to end_layer")
        return self

    @property
    def num_layers(self) -> int:
        """Return total number of layers in range."""
        return self.end_layer - self.start_layer + 1


class StageType(str, Enum):  # noqa: UP042
    """Stage type classification for pipeline sharding and local boundary isolation."""

    CLIENT_EMBEDDING = "client_embedding"
    REMOTE_HIDDEN = "remote_hidden"
    CLIENT_LM_HEAD = "client_lm_head"
    COMPUTE = "compute"


class TaskProposal(BaseModel):
    """Task proposal container for split-inference and pipeline scheduling requests."""

    task_id: str = Field(default="", description="Unique task identifier")
    model_id: str = Field(default="", description="Target model identifier")
    model: str = Field(default="", description="Alias for model identifier")
    total_layers: int = Field(default=32, gt=0, description="Total transformer layer count")
    requirements: dict[str, Any] = Field(default_factory=dict, description="Hardware requirements")
    vram_per_layer_gb: float | None = Field(default=None, description="VRAM per layer in GB")
    num_stages: int | None = Field(default=None, description="Requested total stage count")
    split_inference: bool = Field(
        default=True, description="Whether split-inference path is enabled"
    )


class PipelineStage(BaseModel):
    """Represents a single stage in a pipeline parallel model execution chain."""

    stage_index: int = Field(ge=0, description="Index of this pipeline stage (0-based)")
    total_stages: int = Field(gt=0, description="Total number of stages in pipeline")
    layer_range: LayerRange = Field(description="Layer range assigned to this stage")
    node_id: str = Field(description="ID of node assigned to run this stage")
    model_id: str = Field(default="", description="Target model identifier")
    is_local_boundary: bool = Field(
        default=False, description="Whether stage runs locally on client boundary"
    )
    stage_type: StageType | str = Field(
        default=StageType.COMPUTE,
        description="Stage type: client_embedding, remote_hidden, client_lm_head, or compute",
    )
    is_split_inference: bool = Field(
        default=False, description="Whether stage participates in split inference"
    )

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        """Validate that stage_index < total_stages."""
        if self.stage_index >= self.total_stages:
            raise ValueError("stage_index must be strictly less than total_stages")
        return self

    @property
    def is_first_stage(self) -> bool:
        """Check if this is the first stage in the pipeline."""
        return self.stage_index == 0

    @property
    def is_last_stage(self) -> bool:
        """Check if this is the last stage in the pipeline."""
        return self.stage_index == self.total_stages - 1

    @property
    def num_layers(self) -> int:
        """Return the number of layers handled by this stage."""
        return self.layer_range.num_layers


class TensorPayload(BaseModel):
    """Payload representing serialized tensor activation data across stages."""

    task_id: str = Field(description="Unique pipeline execution task ID")
    stage_index: int = Field(ge=0, description="Stage index sending the payload")
    target_stage_index: int = Field(default=0, ge=0, description="Target pipeline stage index")
    is_split_inference: bool = Field(
        default=False, description="Flag indicating asymmetric split-inference mode"
    )
    tensor_type: str = Field(
        default="intermediate_activation", description="Type of tensor activation"
    )
    data: bytes | list[float] | dict[str, Any] = Field(
        description="Tensor activation data or payload content"
    )
    shape: list[int] = Field(default_factory=list, description="Dimensions of the tensor shape")
    dtype: str = Field(default="float32", description="Data type of tensor values")
    sequence_id: int = Field(default=0, description="Sequential payload frame counter.")
    shm_name: str | None = Field(
        default=None, description="Shared memory block URI for zero-copy IPC."
    )
    is_quantized: bool = Field(
        default=False, description="Whether activation payload uses FP8/FP4 quantization."
    )
    quantization_type: str | None = Field(
        default=None, description="Quantization scheme used (e.g. 'fp8_e4m3')."
    )
    scale_factor: float = Field(
        default=1.0, description="Dynamic scaling factor for dequantization."
    )
    is_speculative: bool = Field(
        default=False, description="Whether payload contains multi-token candidate blocks."
    )
    speculative_block_size: int = Field(
        default=1, description="Number of speculative candidate tokens (K)."
    )

    def validate_split_activation_boundary(self) -> None:
        """Reject payloads that violate the split-inference activation-only boundary."""
        if not self.is_split_inference:
            raise ValueError("Split stage payload must set is_split_inference=True")

        allowed_tensor_types = {"activation", "intermediate_activation"}
        if self.tensor_type not in allowed_tensor_types:
            raise ValueError("Split stage payload tensor_type must be an activation")

        allowed_dtypes = {
            "float16",
            "float32",
            "float64",
            "bfloat16",
            "float8_e4m3",
            "float8_e4m3fn",
        }
        if self.dtype not in allowed_dtypes and not self.is_quantized:
            raise ValueError("Split stage payload dtype must be a floating-point tensor type")

        if not self.shape or any(dim <= 0 for dim in self.shape):
            raise ValueError("Split stage payload shape must contain positive dimensions")

        if isinstance(self.data, dict):
            raise ValueError("Split stage payload data must not contain structured prompt fields")

        if isinstance(self.data, bytes):
            if not self.data:
                raise ValueError("Split stage payload bytes cannot be empty")
            if self.dtype in {"float32", "float64"} and len(self.data) % 4 != 0:
                raise ValueError("Split stage payload bytes must align to float elements")
            return

        if not self.data:
            raise ValueError("Split stage payload data cannot be empty")

        expected_elements = prod(self.shape)
        if expected_elements != len(self.data):
            raise ValueError("Split stage payload data length must match tensor shape")

    def to_framed_bytes(self) -> bytes:
        """Construct binary frame: b'PITP' + 4-byte len + JSON + raw bytes."""
        is_bytes = isinstance(self.data, bytes)
        meta = {
            "task_id": self.task_id,
            "stage_index": self.stage_index,
            "target_stage_index": self.target_stage_index,
            "is_split_inference": self.is_split_inference,
            "tensor_type": self.tensor_type,
            "shape": self.shape,
            "dtype": self.dtype,
            "sequence_id": self.sequence_id,
            "shm_name": self.shm_name,
            "is_bytes": is_bytes,
        }
        meta_bytes = json.dumps(meta).encode("utf-8")
        meta_len = len(meta_bytes)

        raw_payload = self.data if is_bytes else json.dumps(self.data).encode("utf-8")

        return b"PITP" + meta_len.to_bytes(4, "big") + meta_bytes + raw_payload  # type: ignore[operator]

    @classmethod
    def from_framed_bytes(cls, raw: bytes) -> "TensorPayload":
        """Parse binary frame starting with b'PITP' or fall back to standard JSON parsing."""
        if not raw.startswith(b"PITP"):
            meta = json.loads(raw.decode("utf-8"))
            return cls(**meta)

        meta_len = int.from_bytes(raw[4:8], "big")
        meta_bytes = raw[8 : 8 + meta_len]
        meta = json.loads(meta_bytes.decode("utf-8"))
        raw_payload = raw[8 + meta_len :]

        if meta.get("is_bytes", False):
            data: bytes | list[float] | dict[str, Any] = raw_payload
        else:
            data = json.loads(raw_payload.decode("utf-8"))

        return cls(
            task_id=meta["task_id"],
            stage_index=meta["stage_index"],
            target_stage_index=meta.get("target_stage_index", 0),
            is_split_inference=meta.get("is_split_inference", False),
            tensor_type=meta.get("tensor_type", "intermediate_activation"),
            data=data,
            shape=meta.get("shape", []),
            dtype=meta.get("dtype", "float32"),
            sequence_id=meta.get("sequence_id", 0),
            shm_name=meta.get("shm_name"),
        )


class PipelineConfig(BaseModel):
    """Configuration for an entire pipeline parallel execution across nodes."""

    task_id: str = Field(description="Unique task identifier")
    model_id: str = Field(description="Target model identifier")
    total_layers: int = Field(gt=0, description="Total number of model layers")
    stages: list[PipelineStage] = Field(
        default_factory=list, description="Stages composing the pipeline"
    )

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        """Validate stage bounds and continuity across stages."""
        if not self.stages:
            return self

        # Ensure stages are ordered and contiguous
        for idx, stage in enumerate(self.stages):
            if stage.stage_index != idx:
                raise ValueError(
                    f"Stage index mismatch at position {idx}: got {stage.stage_index}"
                )

        # Check total layers coverage
        if self.stages[0].layer_range.start_layer != 0:
            raise ValueError("First pipeline stage must start at layer 0")

        last_stage = self.stages[-1]
        is_split = (
            last_stage.is_split_inference
            or last_stage.is_local_boundary
            or last_stage.stage_type in (StageType.CLIENT_LM_HEAD, "client_lm_head")
        )
        expected_end = self.total_layers if is_split else self.total_layers - 1
        if last_stage.layer_range.end_layer != expected_end:
            raise ValueError(
                f"Last pipeline stage end layer ({last_stage.layer_range.end_layer}) "
                f"must match expected end layer ({expected_end})"
            )

        for i in range(len(self.stages) - 1):
            curr_end = self.stages[i].layer_range.end_layer
            next_start = self.stages[i + 1].layer_range.start_layer
            if curr_end + 1 != next_start:
                raise ValueError(
                    f"Discontinuity between stage {i} (end {curr_end}) and "
                    f"stage {i + 1} (start {next_start})"
                )

        return self

    @property
    def num_stages(self) -> int:
        """Return number of stages in pipeline."""
        return len(self.stages)


class DraftBlockPayload(BaseModel):
    """Speculative candidate block payload sent from local edge gateway over WAN."""

    task_id: str = Field(description="Unique task identifier")
    sequence_start_id: int = Field(default=0, ge=0, description="Starting sequence position index")
    speculative_k: int = Field(
        default=5, ge=1, le=16, description="Number of candidate tokens (K)"
    )
    candidate_tokens: list[int] = Field(default_factory=list, description="Candidate token IDs")
    draft_logprobs: list[float] = Field(default_factory=list, description="Draft logprobs")
    activation_payload: TensorPayload = Field(description="Batched activation tensor payload")


class VerificationResult(BaseModel):
    """Result of single-pass speculative verification over WAN link."""

    task_id: str = Field(description="Unique task identifier")
    sequence_start_id: int = Field(default=0, ge=0, description="Starting sequence position")
    n_accepted: int = Field(default=1, ge=0, le=16, description="Number of accepted tokens")
    accepted_tokens: list[int] = Field(default_factory=list, description="Accepted token IDs")
    correction_token: int | None = Field(default=None, description="Correction token ID")
    verified_activations: TensorPayload | None = Field(
        default=None, description="Verified output activation payload"
    )
