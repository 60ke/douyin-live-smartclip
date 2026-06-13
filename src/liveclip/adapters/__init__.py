"""liveclip 适配器层。"""

from liveclip.adapters.douyin import (
    DouyinLiveChecker,
    DouyinLiveStatus,
    DouyinRecorder,
    DouyinResolver,
    DouyinRoomInfo,
    DouyinStreamFetcher,
)
from liveclip.adapters.ffmpeg import FFmpegClipper, FFmpegCommandBuilder, FFmpegConverter
from liveclip.adapters.funasr import FunASRTranscriber, HotwordManager
from liveclip.adapters.llm import (
    LLMClient,
    PromptTemplate,
    parse_boundary_validation,
    parse_clip_plan,
)

__all__ = [
    # douyin
    "DouyinRoomInfo",
    "DouyinResolver",
    "DouyinLiveStatus",
    "DouyinLiveChecker",
    "DouyinStreamFetcher",
    "DouyinRecorder",
    # ffmpeg
    "FFmpegConverter",
    "FFmpegClipper",
    "FFmpegCommandBuilder",
    # funasr
    "FunASRTranscriber",
    "HotwordManager",
    # llm
    "LLMClient",
    "PromptTemplate",
    "parse_clip_plan",
    "parse_boundary_validation",
]
