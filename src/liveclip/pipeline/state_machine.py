"""流水线状态机，管理步骤顺序与跳过逻辑。"""

from __future__ import annotations

from liveclip.domain.enums import StepName
from liveclip.domain.models import PipelineConfig
from liveclip.observability import get_logger

logger = get_logger(__name__)

# 完整的流水线步骤顺序
PIPELINE_STEPS: list[StepName] = [
    StepName.RECORD_TS,
    StepName.CONVERT_MP4,
    StepName.TRANSCRIBE,
    StepName.PREPROCESS_SUBTITLE,
    StepName.PLAN_CLIPS,
    StepName.VALIDATE_BOUNDARY,
    StepName.EXPORT_CLIPS,
    StepName.FINALIZE,
]

# 可通过 PipelineConfig 控制是否执行的步骤
_CONFIGURABLE_STEPS: dict[StepName, str] = {
    StepName.CONVERT_MP4: "convert_mp4",
    StepName.TRANSCRIBE: "transcribe",
    StepName.PREPROCESS_SUBTITLE: "preprocess_subtitle",
    StepName.PLAN_CLIPS: "plan_clips",
    StepName.VALIDATE_BOUNDARY: "validate_boundary",
    StepName.EXPORT_CLIPS: "export_clips",
}


def should_run_step(step: StepName, pipeline_config: PipelineConfig) -> bool:
    """判断步骤是否应该执行。

    RECORD_TS 和 FINALIZE 始终执行；其余步骤根据 PipelineConfig
    中对应的开关决定。

    Args:
        step: 步骤名称。
        pipeline_config: 流水线配置。

    Returns:
        True 表示应执行，False 表示应跳过。
    """
    config_attr = _CONFIGURABLE_STEPS.get(step)
    if config_attr is None:
        # RECORD_TS / FINALIZE 不可跳过
        return True
    return bool(getattr(pipeline_config, config_attr))


def get_enabled_steps(pipeline_config: PipelineConfig) -> list[StepName]:
    """获取所有已启用的步骤（按顺序）。

    Args:
        pipeline_config: 流水线配置。

    Returns:
        已启用步骤名称列表。
    """
    return [s for s in PIPELINE_STEPS if should_run_step(s, pipeline_config)]


def get_next_step(
    current: StepName | None,
    pipeline_config: PipelineConfig,
) -> StepName | None:
    """获取当前步骤之后的下一个启用步骤。

    Args:
        current: 当前步骤名称，为 None 时返回第一个启用步骤。
        pipeline_config: 流水线配置。

    Returns:
        下一个启用的步骤名称，若无则返回 None。
    """
    enabled = get_enabled_steps(pipeline_config)

    if current is None:
        return enabled[0] if enabled else None

    try:
        idx = enabled.index(current)
    except ValueError:
        logger.warning("step_not_in_enabled_list", step=current)
        return None

    next_idx = idx + 1
    if next_idx < len(enabled):
        return enabled[next_idx]
    return None
