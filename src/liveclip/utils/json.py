from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any


def extract_json_object(text: str) -> dict | None:
    """Extract the first JSON object from text, typically an LLM response.

    Handles markdown code fences (````json ... ````) and raw text containing
    a JSON object.  Returns ``None`` when no valid object is found.

    Args:
        text: Raw text that may contain a JSON object.

    Returns:
        Parsed dict, or ``None`` if extraction fails.
    """
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if fence_match:
        candidate = fence_match.group(1).strip()
        try:
            result = json.loads(candidate)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : i + 1]
                try:
                    result = json.loads(candidate)
                    if isinstance(result, dict):
                        return result
                except json.JSONDecodeError:
                    continue
    return None


def extract_json_value(text: str) -> Any | None:
    """Extract any JSON value from text.

    Similar to :func:`extract_json_object` but accepts any valid JSON
    value (object, array, string, number, bool, null).

    Args:
        text: Raw text that may contain a JSON value.

    Returns:
        Parsed JSON value, or ``None`` if extraction fails.
    """
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if fence_match:
        candidate = fence_match.group(1).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    for start_char in ("{", "[", '"'):
        idx = text.find(start_char)
        if idx == -1:
            continue
        if start_char in ("{", "["):
            close_char = "}" if start_char == "{" else "]"
            depth = 0
            for i in range(idx, len(text)):
                if text[i] == start_char:
                    depth += 1
                elif text[i] == close_char:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[idx : i + 1])
                        except json.JSONDecodeError:
                            break
        elif start_char == '"':
            i = idx + 1
            while i < len(text):
                if text[i] == "\\" and i + 1 < len(text):
                    i += 2
                    continue
                if text[i] == '"':
                    try:
                        return json.loads(text[idx : i + 1])
                    except json.JSONDecodeError:
                        break
                i += 1

    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        return None


_CHINESE_ENUM_MAP: dict[str, str] = {
    "高": "high",
    "中": "medium",
    "低": "low",
    "是": "true",
    "否": "false",
    "真": "true",
    "假": "false",
    "正面": "positive",
    "负面": "negative",
    "中性": "neutral",
}


def normalize_enum_value(value: str, allowed: Sequence[str], default: str) -> str:
    """Normalize an enum value with case-insensitive and Chinese mapping.

    Strips whitespace, lowercases, and checks against *allowed*.  Also
    maps common Chinese alternatives before matching.

    Args:
        value: Raw value to normalize.
        allowed: Sequence of valid canonical values (lowercase).
        default: Fallback value when normalization fails.

    Returns:
        A value from *allowed*, or *default*.
    """
    cleaned = value.strip().lower()

    if cleaned in allowed:
        return cleaned

    mapped = _CHINESE_ENUM_MAP.get(value.strip())
    if mapped is not None and mapped in allowed:
        return mapped

    return default


def clamp_score(value: float, min_val: float = 0.0, max_val: float = 1.0) -> float:
    """Clamp a numeric score to the given range.

    Args:
        value: The score to clamp.
        min_val: Minimum allowed value.
        max_val: Maximum allowed value.

    Returns:
        *value* clamped to ``[min_val, max_val]``.
    """
    return max(min_val, min(max_val, value))
