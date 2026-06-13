from __future__ import annotations

from pathlib import Path

import pytest

from liveclip.domain.value_objects import FilePath, SafeFilename, Timecode


class TestTimecode:
    """Tests for Timecode value object."""

    def test_from_string_hms_ms(self) -> None:
        tc = Timecode.from_string("01:23:45.678")
        assert tc.seconds == pytest.approx(1 * 3600 + 23 * 60 + 45 + 0.678)

    def test_from_string_hms(self) -> None:
        tc = Timecode.from_string("01:23:45")
        assert tc.seconds == pytest.approx(1 * 3600 + 23 * 60 + 45)

    def test_from_string_zero(self) -> None:
        tc = Timecode.from_string("00:00:00.000")
        assert tc.seconds == 0.0

    def test_str_format(self) -> None:
        tc = Timecode(3723.456)
        assert str(tc) == "01:02:03.456"

    def test_str_format_zero(self) -> None:
        tc = Timecode(0.0)
        assert str(tc) == "00:00:00.000"

    def test_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            Timecode(-1.0)

    def test_invalid_format_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid timecode"):
            Timecode.from_string("invalid")

    def test_equality(self) -> None:
        assert Timecode(10.0) == Timecode(10.0)
        assert Timecode(10.0) != Timecode(11.0)

    def test_comparison_lt(self) -> None:
        assert Timecode(5.0) < Timecode(10.0)
        assert not Timecode(10.0) < Timecode(5.0)

    def test_comparison_le(self) -> None:
        assert Timecode(5.0) <= Timecode(5.0)
        assert Timecode(5.0) <= Timecode(10.0)

    def test_comparison_gt(self) -> None:
        assert Timecode(10.0) > Timecode(5.0)
        assert not Timecode(5.0) > Timecode(10.0)

    def test_comparison_ge(self) -> None:
        assert Timecode(10.0) >= Timecode(10.0)
        assert Timecode(10.0) >= Timecode(5.0)

    def test_hash(self) -> None:
        s = {Timecode(5.0), Timecode(5.0), Timecode(10.0)}
        assert len(s) == 2

    def test_properties(self) -> None:
        tc = Timecode(3661.5)
        assert tc.hh == 1
        assert tc.mm == 1
        assert tc.ss == 1
        assert tc.mmm == 500


class TestSafeFilename:
    """Tests for SafeFilename value object."""

    def test_normal_name(self) -> None:
        sf = SafeFilename("hello world")
        assert sf.sanitized == "hello world"
        assert str(sf) == "hello world"

    def test_illegal_chars_removed(self) -> None:
        sf = SafeFilename('test<>:"/\\|?*file')
        assert sf.sanitized == "testfile"

    def test_empty_becomes_default(self) -> None:
        sf = SafeFilename("")
        assert sf.sanitized == "未命名片段"

    def test_dots_and_spaces_stripped(self) -> None:
        sf = SafeFilename("  ...test...  ")
        assert sf.sanitized == "test"

    def test_long_name_truncated(self) -> None:
        sf = SafeFilename("a" * 200)
        assert len(sf.sanitized) <= 80

    def test_original_preserved(self) -> None:
        sf = SafeFilename("bad<>name")
        assert sf.original == "bad<>name"
        assert sf.sanitized == "badname"

    def test_equality(self) -> None:
        assert SafeFilename("test") == SafeFilename("test")
        assert SafeFilename("test") != SafeFilename("other")

    def test_hash(self) -> None:
        s = {SafeFilename("test"), SafeFilename("test")}
        assert len(s) == 1


class TestFilePath:
    """Tests for FilePath value object."""

    def test_creation_from_string(self) -> None:
        fp = FilePath("/tmp/test.txt")
        assert fp.name == "test.txt"
        assert fp.suffix == ".txt"
        assert fp.stem == "test"

    def test_creation_from_path(self) -> None:
        fp = FilePath(Path("/tmp/test.txt"))
        assert fp.name == "test.txt"

    def test_parent(self) -> None:
        fp = FilePath("/tmp/sub/test.txt")
        parent = fp.parent
        assert isinstance(parent, FilePath)
        assert str(parent) == "/tmp/sub"

    def test_joinpath(self) -> None:
        fp = FilePath("/tmp")
        child = fp.joinpath("sub", "file.txt")
        assert isinstance(child, FilePath)
        assert str(child) == "/tmp/sub/file.txt"

    def test_equality(self) -> None:
        assert FilePath("/tmp/a") == FilePath("/tmp/a")
        assert FilePath("/tmp/a") != FilePath("/tmp/b")

    def test_str(self) -> None:
        fp = FilePath("/tmp/test.txt")
        assert str(fp) == "/tmp/test.txt"

    def test_repr(self) -> None:
        fp = FilePath("/tmp/test.txt")
        assert "FilePath" in repr(fp)
