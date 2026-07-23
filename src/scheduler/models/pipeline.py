"""Pipeline scheduling models for model layer sharding."""

from typing import Self

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


class PipelineStage(BaseModel):
    """Represents a single stage in a pipeline parallel model execution chain."""

    stage_index: int = Field(ge=0, description="Index of this pipeline stage (0-based)")
    total_stages: int = Field(gt=0, description="Total number of stages in pipeline")
    layer_range: LayerRange = Field(description="Layer range assigned to this stage")
    node_id: str = Field(description="ID of node assigned to run this stage")
    model_id: str = Field(default="", description="Target model identifier")

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
        if last_stage.layer_range.end_layer != self.total_layers - 1:
            raise ValueError(
                f"Last pipeline stage end layer ({last_stage.layer_range.end_layer}) "
                f"must match total_layers - 1 ({self.total_layers - 1})"
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
