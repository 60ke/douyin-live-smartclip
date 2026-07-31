"""导出路由 — 为外部同步消费端提供切片列表接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from liveclip.api.deps import get_db_session
from liveclip.schemas.export import (
    ExportClipsResponse,
    ExportCursor,
    normalize_room_ids,
)
from liveclip.services.export_service import list_completed_clips

router = APIRouter(prefix="/api/v1/media/export", tags=["export"])


@router.get("/clips", response_model=ExportClipsResponse)
async def export_clips(
    cursor: str | None = Query(None, description="上一页返回的 next_cursor（base64 编码）"),
    limit: int = Query(50, ge=1, le=200, description="每页数量"),
    room_ids: list[int] | None = Query(
        None,
        description="限定直播间 ID，可重复传入，例如 room_ids=1&room_ids=2",
    ),
    session: AsyncSession = Depends(get_db_session),
) -> ExportClipsResponse:
    """返回已完成的切片列表，按创建时间升序，支持游标分页和直播间多选。"""
    try:
        selected_room_ids = normalize_room_ids(room_ids)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    parsed_cursor: ExportCursor | None = None
    if cursor:
        try:
            parsed_cursor = ExportCursor.decode(cursor)
            parsed_cursor.validate_room_filter(selected_room_ids)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    return await list_completed_clips(
        session,
        cursor=parsed_cursor,
        limit=limit,
        room_ids=selected_room_ids,
    )
