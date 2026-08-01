"""导出路由 — 为外部同步消费端提供直播间和切片列表接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from liveclip.api.deps import get_db_session
from liveclip.schemas.export import ExportClipsResponse, ExportCursor, ExportRoomsResponse
from liveclip.services.export_service import list_completed_clips, list_export_rooms

router = APIRouter(prefix="/api/v1/media/export", tags=["export"])


@router.get("/rooms", response_model=ExportRoomsResponse)
async def export_rooms(
    session: AsyncSession = Depends(get_db_session),
) -> ExportRoomsResponse:
    """返回可供同步客户端选择的全部直播间。"""
    return await list_export_rooms(session)


@router.get("/clips", response_model=ExportClipsResponse)
async def export_clips(
    cursor: str | None = Query(None, description="上一页返回的 next_cursor（base64 编码）"),
    limit: int = Query(50, ge=1, le=200, description="每页数量"),
    room_ids: list[str] | None = Query(
        None,
        description="直播间 ID，可传逗号分隔值或重复参数，例如 room_ids=1,2",
    ),
    session: AsyncSession = Depends(get_db_session),
) -> ExportClipsResponse:
    """返回已完成的切片列表，按创建时间升序，支持游标分页和直播间筛选。

    调用方首次请求不传 cursor，之后将响应中的 next_cursor 作为下页的 cursor 传入。
    next_cursor 为 null 时表示已到末尾。游标会绑定 room_ids 筛选条件，筛选变化后
    必须从第一页重新请求。
    """
    parsed_room_ids = _parse_room_ids(room_ids)
    parsed_cursor: ExportCursor | None = None
    if cursor:
        try:
            parsed_cursor = ExportCursor.decode(cursor)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

        cursor_filter = tuple(parsed_cursor.room_ids or ())
        requested_filter = tuple(parsed_room_ids or ())
        if cursor_filter != requested_filter:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="cursor 与 room_ids 筛选条件不匹配，请从第一页重新请求",
            )

    return await list_completed_clips(
        session,
        cursor=parsed_cursor,
        limit=limit,
        room_ids=parsed_room_ids,
    )


def _parse_room_ids(raw_values: list[str] | None) -> tuple[int, ...] | None:
    """解析逗号分隔或重复传递的 room_ids，并返回去重后的升序元组。"""
    if not raw_values:
        return None

    parsed: set[int] = set()
    try:
        for raw_value in raw_values:
            for item in raw_value.split(","):
                stripped = item.strip()
                if not stripped:
                    continue
                room_id = int(stripped)
                if room_id <= 0:
                    raise ValueError("room_id must be positive")
                parsed.add(room_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="room_ids 必须是正整数列表",
        ) from exc

    return tuple(sorted(parsed)) or None
