"""流水线模块：上下文、状态机与步骤。"""

from __future__ import annotations

from liveclip.pipeline.context import PipelineContext
from liveclip.pipeline.state_machine import (
    PIPELINE_STEPS,
    get_enabled_steps,
    get_next_step,
    should_run_step,
)
from liveclip.pipeline.steps import (
    BaseStep,
    ConvertMp4Step,
    ExportClipsStep,
    FinalizeStep,
    PlanClipsStep,
    PreprocessSubtitleStep,
    RecordTsStep,
    TranscribeStep,
    ValidateBoundaryStep,
)

__all__ = [
    # 上下文
    "PipelineContext",
    # 状态机
    "PIPELINE_STEPS",
    "get_enabled_steps",
    "get_next_step",
    "should_run_step",
    # 步骤基类
    "BaseStep",
    # 步骤实现
    "RecordTsStep",
    "ConvertMp4Step",
    "TranscribeStep",
    "PreprocessSubtitleStep",
    "PlanClipsStep",
    "ValidateBoundaryStep",
    "ExportClipsStep",
    "FinalizeStep",
]
