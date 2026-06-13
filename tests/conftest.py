from __future__ import annotations

from pathlib import Path

import pytest

from liveclip.domain.models import ClipSegment, SubtitleEntry


@pytest.fixture()
def tmp_dir(tmp_path: Path) -> Path:
    """Provide a temporary directory for tests."""
    return tmp_path


@pytest.fixture()
def sample_srt_content() -> str:
    """Return a sample SRT string with 10 Chinese subtitle entries."""
    return (
        "1\n"
        "00:00:01,000 --> 00:00:03,500\n"
        "大家好，欢迎来到直播间\n"
        "\n"
        "2\n"
        "00:00:03,800 --> 00:00:06,200\n"
        "今天我们来聊聊AI绘图\n"
        "\n"
        "3\n"
        "00:00:06,500 --> 00:00:10,000\n"
        "首先打开GEO的网站\n"
        "\n"
        "4\n"
        "00:00:10,300 --> 00:00:15,800\n"
        "然后选择文生图功能\n"
        "\n"
        "5\n"
        "00:00:16,100 --> 00:00:20,500\n"
        "输入你想要的描述词\n"
        "\n"
        "6\n"
        "00:00:20,800 --> 00:00:25,000\n"
        "点击生成，等待几秒钟\n"
        "\n"
        "7\n"
        "00:00:25,300 --> 00:00:30,000\n"
        "效果图就出来了，非常简单\n"
        "\n"
        "8\n"
        "00:00:30,500 --> 00:00:35,200\n"
        "接下来我们看看图生图\n"
        "\n"
        "9\n"
        "00:00:35,500 --> 00:00:40,000\n"
        "上传一张参考图片\n"
        "\n"
        "10\n"
        "00:00:40,300 --> 00:00:45,800\n"
        "然后调整参数，生成新的效果图\n"
    )


@pytest.fixture()
def sample_subtitles() -> list[SubtitleEntry]:
    """Return a list of SubtitleEntry objects for testing."""
    return [
        SubtitleEntry(index=1, start=1.0, end=3.5, text="大家好，欢迎来到直播间"),
        SubtitleEntry(index=2, start=3.8, end=6.2, text="今天我们来聊聊AI绘图"),
        SubtitleEntry(index=3, start=6.5, end=10.0, text="首先打开GEO的网站"),
        SubtitleEntry(index=4, start=10.3, end=15.8, text="然后选择文生图功能"),
        SubtitleEntry(index=5, start=16.1, end=20.5, text="输入你想要的描述词"),
        SubtitleEntry(index=6, start=20.8, end=25.0, text="点击生成，等待几秒钟"),
        SubtitleEntry(index=7, start=25.3, end=30.0, text="效果图就出来了，非常简单"),
        SubtitleEntry(index=8, start=30.5, end=35.2, text="接下来我们看看图生图"),
        SubtitleEntry(index=9, start=35.5, end=40.0, text="上传一张参考图片"),
        SubtitleEntry(index=10, start=40.3, end=45.8, text="然后调整参数，生成新的效果图"),
    ]


@pytest.fixture()
def sample_clip_segments() -> list[ClipSegment]:
    """Return a list of ClipSegment objects for testing."""
    return [
        ClipSegment(
            title="AI绘图入门",
            start_subtitle_index=1,
            end_subtitle_index=4,
            score=0.85,
            reason="介绍了AI绘图的基本流程",
        ),
        ClipSegment(
            title="生成效果图",
            start_subtitle_index=5,
            end_subtitle_index=7,
            score=0.72,
            reason="演示了如何生成效果图",
        ),
        ClipSegment(
            title="图生图功能",
            start_subtitle_index=8,
            end_subtitle_index=10,
            score=0.65,
            reason="介绍了图生图功能",
        ),
    ]


@pytest.fixture()
def fixtures_dir() -> Path:
    """Return the path to the tests/fixtures directory."""
    return Path(__file__).parent / "fixtures"
