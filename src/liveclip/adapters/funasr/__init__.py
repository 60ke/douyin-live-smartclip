"""FunASR 语音转写适配器。"""

from liveclip.adapters.funasr.hotwords import HotwordManager
from liveclip.adapters.funasr.transcriber import FunASRTranscriber

__all__ = [
    "FunASRTranscriber",
    "HotwordManager",
]
