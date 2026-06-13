"""流水线执行上下文，持有单次流水线运行的全部状态。"""

from __future__ import annotations

from typing import Any

from liveclip.domain.models import (
    ClipSegmentConfig,
    LLMCallConfig,
    PipelineConfig,
    RecordConfig,
    StepResult,
)
from liveclip.observability import get_logger
from liveclip.storage.paths import RunPaths

logger = get_logger(__name__)


class PipelineContext:
    """单次流水线运行的执行上下文。

    聚合运行标识、路径、配置、步骤结果与取消信号，
    在流水线各步骤之间共享状态。

    Attributes:
        run_id: 运行 ID。
        room_id: 直播间 ID。
        task_id: 任务 ID。
        paths: 本次运行的所有文件路径。
        pipeline_config: 流水线步骤开关配置。
        clip_segment_config: 切片分段参数配置。
        llm_call_config: 大模型调用配置。
        record_config: 录制配置。
        cancel_requested: 是否已请求取消。
        step_results: 步骤名称到执行结果的映射。
        metadata: 运行时附加元数据。
    """

    def __init__(
        self,
        run_id: int,
        room_id: int,
        task_id: int,
        paths: RunPaths,
        pipeline_config: PipelineConfig,
        clip_segment_config: ClipSegmentConfig,
        llm_call_config: LLMCallConfig,
        record_config: RecordConfig,
    ) -> None:
        self.run_id = run_id
        self.room_id = room_id
        self.task_id = task_id
        self.paths = paths
        self.pipeline_config = pipeline_config
        self.clip_segment_config = clip_segment_config
        self.llm_call_config = llm_call_config
        self.record_config = record_config
        self.cancel_requested: bool = False
        self.step_results: dict[str, StepResult] = {}
        self.metadata: dict[str, Any] = {}

    def request_cancel(self) -> None:
        """请求取消本次流水线运行。"""
        self.cancel_requested = True
        logger.info("cancel_requested", run_id=self.run_id)

    def is_cancelled(self) -> bool:
        """检查是否已请求取消。"""
        return self.cancel_requested

    def set_step_result(self, step_name: str, result: StepResult) -> None:
        """记录步骤执行结果。

        Args:
            step_name: 步骤名称。
            result: 步骤执行结果。
        """
        self.step_results[step_name] = result
        logger.debug(
            "step_result_set",
            step_name=step_name,
            success=result.success,
            run_id=self.run_id,
        )

    def get_step_result(self, step_name: str) -> StepResult | None:
        """获取步骤执行结果。

        Args:
            step_name: 步骤名称。

        Returns:
            步骤执行结果，若不存在则返回 None。
        """
        return self.step_results.get(step_name)
