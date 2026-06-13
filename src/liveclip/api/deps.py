"""FastAPI 依赖注入。"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from liveclip.db.session import get_session
from liveclip.services import (
    ClipService,
    HotwordService,
    LiveRoomService,
    PromptService,
    RunService,
    TaskService,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """获取异步数据库会话。"""
    async for session in get_session():
        yield session


def get_live_room_service(session: AsyncSession = Depends(get_db_session)) -> LiveRoomService:
    """获取 LiveRoomService 实例。"""
    return LiveRoomService(session)


def get_task_service(session: AsyncSession = Depends(get_db_session)) -> TaskService:
    """获取 TaskService 实例。"""
    return TaskService(session)


def get_run_service(session: AsyncSession = Depends(get_db_session)) -> RunService:
    """获取 RunService 实例。"""
    return RunService(session)


def get_clip_service(session: AsyncSession = Depends(get_db_session)) -> ClipService:
    """获取 ClipService 实例。"""
    return ClipService(session)


def get_prompt_service(session: AsyncSession = Depends(get_db_session)) -> PromptService:
    """获取 PromptService 实例。"""
    return PromptService(session)


def get_hotword_service(session: AsyncSession = Depends(get_db_session)) -> HotwordService:
    """获取 HotwordService 实例。"""
    return HotwordService(session)
