"""Prompt 配置管理服务。"""

from __future__ import annotations

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from liveclip.db.models import PromptProfile
from liveclip.db.repositories.prompt_repo import PromptProfileRepository
from liveclip.schemas.prompt import PromptProfileCreate, PromptProfileUpdate

logger = structlog.get_logger(__name__)


class PromptService:
    """Prompt 配置业务逻辑层，封装 CRUD 与查询操作。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = PromptProfileRepository()

    async def create(self, data: PromptProfileCreate) -> PromptProfile:
        """创建 Prompt 配置。"""
        profile = await self._repo.create(
            self._session,
            name=data.name,
            step_name=data.step_name,
            template_text=data.template_text,
            description=data.description,
            is_active=data.is_active,
        )
        await self._session.flush()
        logger.info("Prompt 配置已创建", profile_id=profile.id, name=data.name)
        return profile

    async def get_by_id(self, profile_id: int) -> PromptProfile | None:
        """根据 ID 获取 Prompt 配置。"""
        return await self._repo.get_by_id(self._session, profile_id)

    async def get_by_name(self, name: str) -> PromptProfile | None:
        """根据名称获取 Prompt 配置。"""
        return await self._repo.get_by_name(self._session, name)

    async def get_active_by_step(self, step_name: str) -> PromptProfile | None:
        """根据步骤名称获取激活的 Prompt 配置。"""
        return await self._repo.get_active_by_step(self._session, step_name)

    async def get_all(self, offset: int = 0, limit: int = 100) -> tuple[list[PromptProfile], int]:
        """获取 Prompt 配置列表及总数。"""
        items = await self._repo.get_all(self._session, offset=offset, limit=limit)
        count_stmt = select(func.count()).select_from(PromptProfile)
        result = await self._session.execute(count_stmt)
        total = result.scalar_one()
        return items, total

    async def update(self, profile_id: int, data: PromptProfileUpdate) -> PromptProfile | None:
        """更新 Prompt 配置。"""
        update_fields = data.model_dump(exclude_unset=True)
        if not update_fields:
            return await self._repo.get_by_id(self._session, profile_id)
        try:
            profile = await self._repo.update(self._session, profile_id, **update_fields)
        except ValueError:
            return None
        await self._session.flush()
        logger.info(
            "Prompt 配置已更新",
            profile_id=profile_id,
            fields=list(update_fields.keys()),
        )
        return profile

    async def delete(self, profile_id: int) -> bool:
        """删除 Prompt 配置。"""
        result = await self._repo.delete(self._session, profile_id)
        if result:
            await self._session.flush()
            logger.info("Prompt 配置已删除", profile_id=profile_id)
        return result
