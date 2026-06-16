"""直播间 CRUD 路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from liveclip.api.deps import get_db_session, get_live_room_service
from liveclip.schemas.live_room import (
    LiveRoomCreate,
    LiveRoomListResponse,
    LiveRoomResponse,
    LiveRoomUpdate,
)
from liveclip.services import LiveRoomService
from liveclip.utils.timezone import as_china_aware

router = APIRouter(prefix="/api/v1/live-rooms", tags=["live-rooms"])


def _apply_tz(room_response: LiveRoomResponse) -> LiveRoomResponse:
    """将 LiveRoomResponse 中的 datetime 字段转换为东八区带时区时间。"""
    data = room_response.model_dump()
    for key in ("created_at", "updated_at"):
        if key in data and data[key] is not None:
            data[key] = as_china_aware(data[key])
    return LiveRoomResponse(**data)


@router.post("/", response_model=LiveRoomResponse, status_code=status.HTTP_201_CREATED)
async def create_live_room(
    body: LiveRoomCreate,
    session: AsyncSession = Depends(get_db_session),
    service: LiveRoomService = Depends(get_live_room_service),
) -> LiveRoomResponse:
    """创建直播间。"""
    room = await service.create(body)
    await session.flush()
    await session.refresh(room)
    response = _apply_tz(LiveRoomResponse.model_validate(room))
    await session.commit()
    return response


@router.get("/", response_model=LiveRoomListResponse)
async def list_live_rooms(
    offset: int = 0,
    limit: int = 100,
    session: AsyncSession = Depends(get_db_session),
    service: LiveRoomService = Depends(get_live_room_service),
) -> LiveRoomListResponse:
    """获取直播间列表。"""
    items, total = await service.get_all(offset=offset, limit=limit)
    response = LiveRoomListResponse(
        items=[_apply_tz(LiveRoomResponse.model_validate(r)) for r in items],
        total=total,
    )
    await session.commit()
    return response


@router.get("/{room_id}", response_model=LiveRoomResponse)
async def get_live_room(
    room_id: int,
    session: AsyncSession = Depends(get_db_session),
    service: LiveRoomService = Depends(get_live_room_service),
) -> LiveRoomResponse:
    """获取单个直播间。"""
    room = await service.get_by_id(room_id)
    if room is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="直播间不存在")
    response = _apply_tz(LiveRoomResponse.model_validate(room))
    await session.commit()
    return response


@router.put("/{room_id}", response_model=LiveRoomResponse)
async def update_live_room(
    room_id: int,
    body: LiveRoomUpdate,
    session: AsyncSession = Depends(get_db_session),
    service: LiveRoomService = Depends(get_live_room_service),
) -> LiveRoomResponse:
    """更新直播间。"""
    room = await service.update(room_id, body)
    if room is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="直播间不存在")
    await session.flush()
    await session.refresh(room)
    response = _apply_tz(LiveRoomResponse.model_validate(room))
    await session.commit()
    return response


@router.delete("/{room_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_live_room(
    room_id: int,
    session: AsyncSession = Depends(get_db_session),
    service: LiveRoomService = Depends(get_live_room_service),
) -> None:
    """删除直播间。"""
    deleted = await service.delete(room_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="直播间不存在")
    await session.commit()
