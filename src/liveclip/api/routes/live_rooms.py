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

router = APIRouter(prefix="/api/v1/live-rooms", tags=["live-rooms"])


@router.post("/", response_model=LiveRoomResponse, status_code=status.HTTP_201_CREATED)
async def create_live_room(
    body: LiveRoomCreate,
    session: AsyncSession = Depends(get_db_session),
    service: LiveRoomService = Depends(get_live_room_service),
) -> LiveRoomResponse:
    """创建直播间。"""
    room = await service.create(body)
    await session.commit()
    return LiveRoomResponse.model_validate(room)


@router.get("/", response_model=LiveRoomListResponse)
async def list_live_rooms(
    offset: int = 0,
    limit: int = 100,
    session: AsyncSession = Depends(get_db_session),
    service: LiveRoomService = Depends(get_live_room_service),
) -> LiveRoomListResponse:
    """获取直播间列表。"""
    items, total = await service.get_all(offset=offset, limit=limit)
    await session.commit()
    return LiveRoomListResponse(
        items=[LiveRoomResponse.model_validate(r) for r in items],
        total=total,
    )


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
    await session.commit()
    await session.refresh(room)
    return LiveRoomResponse.model_validate(room)


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
    response = LiveRoomResponse.model_validate(room)
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
