"""媒体文件服务路由 — 为前端提供视频/字幕文件访问。"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse, Response

from liveclip.config import load_settings

router = APIRouter(prefix="/api/v1/media", tags=["media"])


@router.get("/")
async def serve_media(
    path: str = Query(..., description="文件路径（相对于 storage base_dir 或绝对路径）"),
    format: str | None = Query(None, description="强制输出格式，如 vtt"),
) -> Response:
    """提供媒体文件（视频、字幕等）下载/播放。

    支持 SRT 字幕自动转 VTT（添加 ?format=vtt），兼容 HTML5 <track> 标签。
    """
    settings = load_settings()
    base_dir = settings.storage.base_dir.resolve()
    file_path = Path(path).resolve()

    # 安全检查
    try:
        file_path.relative_to(base_dir)
    except ValueError:
        file_path = (base_dir / path).resolve()
        try:
            file_path.relative_to(base_dir)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="拒绝访问：文件路径不在允许的目录范围内",
            ) from exc

    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"文件不存在: {path}",
        )
    if not file_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="路径指向的不是文件",
        )

    suffix = file_path.suffix.lower()

    # SRT → VTT 转换（HTML5 track 需要 VTT 格式）
    if suffix == ".srt" and format == "vtt":
        content = _srt_to_vtt(file_path.read_text(encoding="utf-8"))
        return Response(
            content=content,
            media_type="text/vtt; charset=utf-8",
        )

    media_type_map = {
        ".mp4": "video/mp4",
        ".ts": "video/mp2t",
        ".webm": "video/webm",
        ".srt": "text/plain; charset=utf-8",
        ".vtt": "text/vtt",
        ".ass": "text/plain; charset=utf-8",
        ".json": "application/json",
        ".txt": "text/plain; charset=utf-8",
    }
    media_type = media_type_map.get(suffix, "application/octet-stream")

    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=file_path.name,
    )


def _srt_to_vtt(content: str) -> str:
    """将 SRT 字幕内容转换为 WebVTT 格式。"""
    # 替换时间戳中的逗号为句点 (00:00:00,000 → 00:00:00.000)
    vtt = re.sub(r"(\d{2}:\d{2}:\d{2}),(\d{3})", r"\1.\2", content)
    return "WEBVTT\n\n" + vtt
