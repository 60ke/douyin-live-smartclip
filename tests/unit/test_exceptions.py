from __future__ import annotations

from liveclip.exceptions import (
    LIVE_ROOM_RESOLVE_FAILED,
    LLM_REQUEST_FAILED,
    RECORD_FAILED,
    BoundaryError,
    ClipPlanError,
    ConfigError,
    ExportError,
    FFmpegError,
    FunASRError,
    LiveClipError,
    LiveRoomError,
    LLMError,
    RecordError,
    StorageError,
    WorkerError,
)


class TestLiveClipError:
    """Tests for LiveClipError base exception."""

    def test_creation(self) -> None:
        err = LiveClipError(
            error_code="TEST_ERROR",
            message="测试错误",
        )
        assert err.error_code == "TEST_ERROR"
        assert err.message == "测试错误"
        assert err.details == {}

    def test_with_details(self) -> None:
        err = LiveClipError(
            error_code="TEST_ERROR",
            message="测试错误",
            details={"key": "value"},
        )
        assert err.details == {"key": "value"}

    def test_is_exception(self) -> None:
        err = LiveClipError("CODE", "msg")
        assert isinstance(err, Exception)

    def test_str_is_message(self) -> None:
        err = LiveClipError("CODE", "错误消息")
        assert str(err) == "错误消息"

    def test_repr(self) -> None:
        err = LiveClipError("CODE", "msg")
        r = repr(err)
        assert "LiveClipError" in r
        assert "CODE" in r


class TestErrorCodes:
    """Tests for error code constants."""

    def test_error_codes_are_strings(self) -> None:
        codes = [
            LIVE_ROOM_RESOLVE_FAILED,
            RECORD_FAILED,
            LLM_REQUEST_FAILED,
        ]
        for code in codes:
            assert isinstance(code, str)

    def test_specific_error_codes(self) -> None:
        assert LIVE_ROOM_RESOLVE_FAILED == "LIVE_ROOM_RESOLVE_FAILED"
        assert RECORD_FAILED == "RECORD_FAILED"
        assert LLM_REQUEST_FAILED == "LLM_REQUEST_FAILED"


class TestExceptionHierarchy:
    """Tests for exception class hierarchy."""

    def test_subclass_inheritance(self) -> None:
        assert issubclass(LiveRoomError, LiveClipError)
        assert issubclass(RecordError, LiveClipError)
        assert issubclass(FFmpegError, LiveClipError)
        assert issubclass(FunASRError, LiveClipError)
        assert issubclass(LLMError, LiveClipError)
        assert issubclass(ClipPlanError, LiveClipError)
        assert issubclass(BoundaryError, LiveClipError)
        assert issubclass(ExportError, LiveClipError)
        assert issubclass(StorageError, LiveClipError)
        assert issubclass(ConfigError, LiveClipError)
        assert issubclass(WorkerError, LiveClipError)

    def test_catch_base_class(self) -> None:
        try:
            raise RecordError(RECORD_FAILED, "录制失败")
        except LiveClipError as exc:
            assert exc.error_code == RECORD_FAILED

    def test_subclass_with_details(self) -> None:
        err = LLMError(
            error_code=LLM_REQUEST_FAILED,
            message="请求失败",
            details={"model": "test-model"},
        )
        assert err.details["model"] == "test-model"
