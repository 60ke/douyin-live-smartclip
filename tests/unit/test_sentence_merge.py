from __future__ import annotations

from liveclip.domain.models import SubtitleEntry
from liveclip.subtitle.sentence_merge import (
    end_boundary_quality,
    ends_with_continuation_cue,
    is_new_topic_opener,
    looks_complete,
    merge_fragments,
)


class TestLooksComplete:
    """Tests for looks_complete function."""

    def test_strong_endings(self) -> None:
        assert looks_complete("这是一个句子。") is True
        assert looks_complete("This is a sentence.") is True
        # 对齐旧项目: "这是真的！" 去掉标点后以 "的" 结尾（BAD_SUFFIX），不算完整
        assert looks_complete("这是真的！") is False
        assert looks_complete("真的吗？") is True
        assert looks_complete("继续吧；") is True
        assert looks_complete("等等…") is True

    def test_weak_endings_good_suffix(self) -> None:
        assert looks_complete("这里生成的效果图内，") is True
        assert looks_complete("这样操作之后就可以了，") is True
        assert looks_complete("各位老板应该能理解吧，") is True
        assert looks_complete("内容已经放在项目里面，") is True

    def test_weak_endings_bad_suffix(self) -> None:
        assert looks_complete("然后，") is False
        assert looks_complete("但是，") is False

    def test_no_punctuation(self) -> None:
        assert looks_complete("没有标点的句子") is False

    def test_empty_string(self) -> None:
        assert looks_complete("") is False

    def test_whitespace_only(self) -> None:
        assert looks_complete("   ") is False


class TestEndBoundaryQuality:
    """Tests for end_boundary_quality function."""

    def test_strong(self) -> None:
        assert end_boundary_quality("完成。") == "strong"

    def test_acceptable(self) -> None:
        assert end_boundary_quality("各位老板应该能理解吧，") == "acceptable"

    def test_weak(self) -> None:
        assert end_boundary_quality("未收束") == "weak"

    def test_bad(self) -> None:
        assert end_boundary_quality("然后") == "bad"

    def test_empty(self) -> None:
        assert end_boundary_quality("") == "bad"


class TestIsNewTopicOpener:
    """Tests for is_new_topic_opener function."""

    def test_topic_openers(self) -> None:
        assert is_new_topic_opener("家人们，然后像我们这边门头招牌功能。") is True
        assert is_new_topic_opener("接下来我们看第二点。") is True
        assert is_new_topic_opener("下面给大家讲案例。") is True

    def test_not_topic_opener(self) -> None:
        assert is_new_topic_opener("这是一个普通句子") is False

    def test_empty(self) -> None:
        assert is_new_topic_opener("") is False


class TestEndsWithContinuationCue:
    """Tests for ends_with_continuation_cue function."""

    def test_continuation_cues(self) -> None:
        assert ends_with_continuation_cue("然后") is True
        assert ends_with_continuation_cue("但是") is True
        assert ends_with_continuation_cue("接下来") is True

    def test_no_continuation(self) -> None:
        assert ends_with_continuation_cue("完成。") is False

    def test_empty(self) -> None:
        assert ends_with_continuation_cue("") is False


class TestMergeFragments:
    """Tests for merge_fragments function."""

    def test_merge_short_fragments(self) -> None:
        subtitles = [
            SubtitleEntry(index=1, start=0.0, end=1.0, text="这是"),
            SubtitleEntry(index=2, start=1.1, end=2.0, text="一个"),
            SubtitleEntry(index=3, start=2.1, end=3.0, text="句子。"),
        ]
        result = merge_fragments(subtitles)
        assert len(result) == 1
        assert "句子。" in result[0].text

    def test_already_complete_sentences(self) -> None:
        subtitles = [
            SubtitleEntry(index=1, start=0.0, end=2.0, text="第一句。"),
            SubtitleEntry(index=2, start=3.0, end=5.0, text="第二句。"),
        ]
        result = merge_fragments(subtitles)
        assert len(result) == 2

    def test_empty_input(self) -> None:
        result = merge_fragments([])
        assert result == []

    def test_single_entry(self) -> None:
        subtitles = [SubtitleEntry(index=1, start=0.0, end=2.0, text="只有一句")]
        result = merge_fragments(subtitles)
        assert len(result) == 1
        assert result[0].text == "只有一句"

    def test_re_indexed(self) -> None:
        subtitles = [
            SubtitleEntry(index=5, start=0.0, end=1.0, text="短"),
            SubtitleEntry(index=10, start=1.1, end=2.0, text="句。"),
        ]
        result = merge_fragments(subtitles)
        for i, entry in enumerate(result, 1):
            assert entry.index == i
