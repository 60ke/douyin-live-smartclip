from __future__ import annotations

from liveclip.adapters.funasr.transcriber import FunASRTranscriber


def test_result_to_srt_splits_by_sentence_punctuation() -> None:
    result = [
        {
            "text": "大家好。欢迎",
            "timestamp": [
                [0, 100],
                [100, 200],
                [200, 300],
                [600, 700],
                [700, 800],
            ],
        }
    ]

    srt = FunASRTranscriber._result_to_srt(result)

    assert "1\n00:00:00,000 --> 00:00:00,300\n大家好。" in srt
    assert "2\n00:00:00,600 --> 00:00:00,800\n欢迎" in srt


def test_result_to_srt_does_not_repeat_full_text_for_each_timestamp() -> None:
    result = [{"text": "你好", "timestamp": [[0, 100], [100, 200]]}]

    srt = FunASRTranscriber._result_to_srt(result)

    assert srt.count("你好") == 1
