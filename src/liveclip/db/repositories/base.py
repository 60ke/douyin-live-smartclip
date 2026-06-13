"""通用仓库基类，提供常见 CRUD 操作。"""

from __future__ import annotations

from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from liveclip.db.models import Base

T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    """泛型仓库基类，封装常见数据库操作。"""

    def __init__(self, model: type[T]) -> None:
        self.model = model

    async def get_by_id(self, session: AsyncSession, id: int) -> T | None:
        """根据主键获取单条记录。"""
        return await session.get(self.model, id)

    async def get_all(self, session: AsyncSession, offset: int = 0, limit: int = 100) -> list[T]:
        """获取记录列表，支持分页。"""
        stmt = select(self.model).offset(offset).limit(limit)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, session: AsyncSession, **kwargs: object) -> T:
        """创建新记录。"""
        instance = self.model(**kwargs)
        session.add(instance)
        await session.flush()
        return instance

    async def update(self, session: AsyncSession, id: int, **kwargs: object) -> T:
        """更新已有记录。"""
        instance = await session.get(self.model, id)
        if instance is None:
            raise ValueError(f"{self.model.__name__} id={id} 不存在")
        for key, value in kwargs.items():
            setattr(instance, key, value)
        await session.flush()
        return instance

    async def delete(self, session: AsyncSession, id: int) -> bool:
        """删除记录，返回是否成功。"""
        instance = await session.get(self.model, id)
        if instance is None:
            return False
        await session.delete(instance)
        await session.flush()
        return True
