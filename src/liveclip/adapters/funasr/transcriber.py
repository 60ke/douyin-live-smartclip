"""FunASR 语音转写适配器。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from liveclip.exceptions import FUNASR_TRANSCRIBE_FAILED, FunASRError
from liveclip.observability import get_logger

logger = get_logger(__name__)

ASR_MODEL = "iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
VAD_MODEL = "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"
PUNC_MODEL = "iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch"


class FunASRTranscriber:
    """使用 FunASR 进行语音转写。"""

    def __init__(
        self,
        device: str = "auto",
        model_dir: str | None = None,
    ) -> None:
        self._device = device
        self._model_dir = model_dir
        self._model: Any = None

    def transcribe(
        self,
        video_path: Path,
        output_srt_path: Path,
        hotwords: list[str] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> Path:
        """将视频文件转写为 SRT 字幕文件。

        Args:
            video_path: 输入视频文件路径。
            output_srt_path: 输出 SRT 文件路径。
            hotwords: 可选的热词列表。
            cancel_check: 可选的取消检查回调。

        Returns:
            生成的 SRT 文件路径。

        Raises:
            FunASRError: 转写失败时抛出。
        """
        logger.info(
            "transcribing",
            video_path=str(video_path),
            output_srt_path=str(output_srt_path),
        )

        if cancel_check and cancel_check():
            raise FunASRError(
                FUNASR_TRANSCRIBE_FAILED,
                "转写被取消",
                details={"video_path": str(video_path)},
            )

        try:
            model = self._load_model()
        except FunASRError:
            raise
        except Exception as exc:
            raise FunASRError(
                FUNASR_TRANSCRIBE_FAILED,
                f"加载 FunASR 模型失败: {exc}",
                details={"error": str(exc)},
            ) from exc

        try:
            generate_kwargs: dict[str, Any] = {}
            if hotwords:
                generate_kwargs["hotword"] = " ".join(hotwords)

            result = model.generate(
                input=str(video_path),
                batch_size_s=300,
                **generate_kwargs,
            )
        except Exception as exc:
            raise FunASRError(
                FUNASR_TRANSCRIBE_FAILED,
                f"FunASR 转写失败: {exc}",
                details={"video_path": str(video_path), "error": str(exc)},
            ) from exc

        if cancel_check and cancel_check():
            raise FunASRError(
                FUNASR_TRANSCRIBE_FAILED,
                "转写被取消",
                details={"video_path": str(video_path)},
            )

        if not result:
            raise FunASRError(
                FUNASR_TRANSCRIBE_FAILED,
                f"FunASR 转写结果为空: {video_path}",
                details={"video_path": str(video_path)},
            )

        srt_content = self._result_to_srt(result)

        if not srt_content.strip():
            raise FunASRError(
                FUNASR_TRANSCRIBE_FAILED,
                f"转写结果生成 SRT 内容为空: {video_path}",
                details={"video_path": str(video_path)},
            )

        output_srt_path.parent.mkdir(parents=True, exist_ok=True)
        output_srt_path.write_text(srt_content, encoding="utf-8")

        logger.info(
            "transcription_finished",
            output_srt_path=str(output_srt_path),
            size=len(srt_content),
        )

        return output_srt_path

    def _resolve_device(self) -> str:
        """解析设备字符串，auto 自动选择 cpu/cuda/mps。"""
        if self._device != "auto":
            return self._device

        try:
            import torch

            if torch.cuda.is_available():
                return "cuda"
            if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                return "mps"
        except ImportError:
            pass

        return "cpu"

    def _load_model(self) -> Any:
        """懒加载 FunASR AutoModel。"""
        if self._model is not None:
            return self._model

        try:
            from funasr import AutoModel
        except ImportError as exc:
            raise FunASRError(
                FUNASR_TRANSCRIBE_FAILED,
                "未安装 funasr 包，请执行 pip install funasr",
                details={"error": str(exc)},
            ) from exc

        device = self._resolve_device()
        logger.info("loading_funasr_model", device=device, model_dir=self._model_dir)

        model_kwargs: dict[str, Any] = {
            "model": ASR_MODEL,
            "vad_model": VAD_MODEL,
            "punc_model": PUNC_MODEL,
            "device": device,
            "disable_update": True,
        }
        if self._model_dir:
            model_kwargs["model_hub"] = self._model_dir

        self._model = AutoModel(**model_kwargs)
        return self._model

    @staticmethod
    def _result_to_srt(result: list[dict] | dict) -> str:
        """将 FunASR 结果转换为 SRT 格式字符串。

        Args:
            result: FunASR generate() 的返回值。

        Returns:
            SRT 格式字符串。
        """
        if isinstance(result, dict):
            items = [result]
        elif isinstance(result, list) and result:
            items = result if isinstance(result[0], dict) else result
        else:
            return ""

        lines: list[str] = []
        index = 1

        for item in items:
            text = str(item.get("text", "")).replace("\t", "").replace("\n", "")
            timestamp = item.get("timestamp")
            if not text or not isinstance(timestamp, list):
                continue
            for start_ms, end_ms, seg_text in _split_text_with_timestamps(text, timestamp):
                lines.append(str(index))
                lines.append(f"{_ms_to_srt_time(start_ms)} --> {_ms_to_srt_time(end_ms)}")
                lines.append(seg_text)
                lines.append("")
                index += 1

        return "\n".join(lines)


def _split_text_with_timestamps(
    text: str,
    timestamps: list[object],
    max_chars_per_line: int = 22,
    max_duration_ms: int = 4000,
    pause_threshold_ms: int = 500,
) -> list[tuple[int, int, str]]:
    normalized_timestamps = _normalize_timestamps(timestamps)
    units, mapping = _parse_text_with_timestamps(text, normalized_timestamps)
    strong_punc = "。！？!?"
    weak_punc = "，,；;：:、"
    subtitles: list[tuple[int, int, str]] = []
    sentence = ""
    start_time: int | None = None
    end_time: int | None = None

    for idx, unit in enumerate(units):
        unit_start, unit_end = mapping[idx]
        if start_time is None:
            start_time = unit_start
        sentence += unit
        end_time = unit_end

        duration = end_time - start_time
        next_pause = 0
        if idx + 1 < len(units):
            next_pause = mapping[idx + 1][0] - end_time

        should_split = False
        if sentence[-1] in strong_punc:
            should_split = True
        elif sentence[-1] in weak_punc and len(sentence) >= 12:
            should_split = True
        elif next_pause >= pause_threshold_ms:
            should_split = True
        elif duration >= max_duration_ms:
            should_split = True
        elif len(sentence) >= max_chars_per_line:
            should_split = True

        if should_split:
            subtitles.append((start_time, end_time, sentence))
            sentence = ""
            start_time = None
            end_time = None

    if sentence and start_time is not None and end_time is not None:
        subtitles.append((start_time, end_time, sentence))
    return subtitles


def _normalize_timestamps(timestamps: list[object]) -> list[tuple[int, int]]:
    normalized: list[tuple[int, int]] = []
    for item in timestamps:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            try:
                normalized.append((int(item[0]), int(item[1])))
            except (TypeError, ValueError):
                continue
    return normalized


def _parse_text_with_timestamps(
    text: str,
    timestamps: list[tuple[int, int]],
) -> tuple[list[str], list[tuple[int, int]]]:
    text_units: list[str] = []
    time_mapping: list[tuple[int, int]] = []
    i = 0
    timestamp_idx = 0

    while i < len(text):
        char = text[i]
        if char.isspace():
            i += 1
            continue
        if char.isascii() and (char.isalpha() or char.isdigit()):
            start = i
            while i < len(text) and _char_kind_matches(text[i], char):
                i += 1
            if timestamp_idx < len(timestamps):
                text_units.append(text[start:i])
                time_mapping.append(timestamps[timestamp_idx])
                timestamp_idx += 1
            continue
        if "\u4e00" <= char <= "\u9fff":
            if timestamp_idx < len(timestamps):
                text_units.append(char)
                time_mapping.append(timestamps[timestamp_idx])
                timestamp_idx += 1
            i += 1
            continue
        if text_units:
            text_units[-1] += char
        i += 1

    return text_units, time_mapping


def _char_kind_matches(value: str, seed: str) -> bool:
    if seed.isalpha():
        return value.isascii() and value.isalpha()
    if seed.isdigit():
        return value.isascii() and value.isdigit()
    return False


def _ms_to_srt_time(ms: int) -> str:
    """将毫秒转换为 SRT 时间格式 HH:MM:SS,mmm。"""
    hours = ms // 3_600_000
    minutes = (ms % 3_600_000) // 60_000
    seconds = (ms % 60_000) // 1_000
    millis = ms % 1_000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"
