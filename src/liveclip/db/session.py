"""数据库会话管理。"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

engine: AsyncEngine | None = None
async_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_db(database_url: str) -> None:
    """创建异步引擎和会话工厂。"""
    global engine, async_session_factory  # noqa: PLW0603
    engine = create_async_engine(database_url, echo=False)
    async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖注入用异步会话生成器。"""
    if async_session_factory is None:
        raise RuntimeError("数据库未初始化，请先调用 init_db()")
    async with async_session_factory() as session:
        yield session


def get_session_context() -> AsyncSession:
    """非 FastAPI 场景（worker、CLI）获取会话实例。

    调用方需自行管理会话生命周期（async with / await session.close()）。
    """
    if async_session_factory is None:
        raise RuntimeError("数据库未初始化，请先调用 init_db()")
    return async_session_factory()
