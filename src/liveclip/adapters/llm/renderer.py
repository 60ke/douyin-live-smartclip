"""LLM 响应解析。"""

from __future__ import annotations

from liveclip.observability import get_logger
from liveclip.utils.json import extract_json_object

logger = get_logger(__name__)


def parse_clip_plan(response_text: str) -> dict | None:
    """从 LLM 响应中提取切片方案。

    尝试从响应文本中提取 JSON 对象，返回解析后的切片方案字典。

    Args:
        response_text: LLM 原始响应文本。

    Returns:
        解析后的切片方案字典，提取失败返回 None。
    """
    result = extract_json_object(response_text)
    if result is None:
        logger.warning(
            "clip_plan_parse_failed",
            response_preview=response_text[:200],
        )
        return None

    logger.info("clip_plan_parsed", keys=list(result.keys()))
    return result


def parse_boundary_validation(response_text: str) -> dict | None:
    """从 LLM 响应中提取边界校验结果。

    尝试从响应文本中提取 JSON 对象，返回解析后的边界校验结果字典。

    Args:
        response_text: LLM 原始响应文本。

    Returns:
        解析后的边界校验结果字典，提取失败返回 None。
    """
    result = extract_json_object(response_text)
    if result is None:
        logger.warning(
            "boundary_validation_parse_failed",
            response_preview=response_text[:200],
        )
        return None

    logger.info("boundary_validation_parsed", keys=list(result.keys()))
    return result
