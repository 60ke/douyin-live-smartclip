"""流水线步骤模块。"""

from __future__ import annotations

from liveclip.pipeline.steps.base import BaseStep
from liveclip.pipeline.steps.convert_mp4 import ConvertMp4Step
from liveclip.pipeline.steps.export_clips import ExportClipsStep
from liveclip.pipeline.steps.finalize import FinalizeStep
from liveclip.pipeline.steps.plan_clips import (
    PlanClipsStep,
    deduplicate_segments,
    parse_llm_response,
    split_long_segments,
)
from liveclip.pipeline.steps.preprocess_subtitle import (
    PreprocessSubtitleStep,
    merge_fragments,
    subtitles_to_sentences,
)
from liveclip.pipeline.steps.record_ts import RecordTsStep
from liveclip.pipeline.steps.transcribe import TranscribeStep
from liveclip.pipeline.steps.validate_boundary import (
    ValidateBoundaryStep,
    snap_segment_boundaries,
)

__all__ = [
    "BaseStep",
    "RecordTsStep",
    "ConvertMp4Step",
    "TranscribeStep",
    "PreprocessSubtitleStep",
    "PlanClipsStep",
    "ValidateBoundaryStep",
    "ExportClipsStep",
    "FinalizeStep",
    # 辅助函数
    "deduplicate_segments",
    "split_long_segments",
    "parse_llm_response",
    "merge_fragments",
    "subtitles_to_sentences",
    "snap_segment_boundaries",
]
