"""热词词典管理服务。"""

from __future__ import annotations

import json

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from liveclip.db.models import HotwordDict
from liveclip.db.repositories.hotword_repo import HotwordDictRepository
from liveclip.schemas.hotword import HotwordDictCreate, HotwordDictUpdate

logger = structlog.get_logger(__name__)


class HotwordService:
    """热词词典业务逻辑层，封装 CRUD 与查询操作。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = HotwordDictRepository()

    async def create(self, data: HotwordDictCreate) -> HotwordDict:
        """创建热词词典。"""
        words_json = json.dumps(data.words, ensure_ascii=False)
        hotword_dict = await self._repo.create(
            self._session,
            name=data.name,
            words_json=words_json,
            is_active=data.is_active,
        )
        await self._session.flush()
        logger.info("热词词典已创建", dict_id=hotword_dict.id, name=data.name)
        return hotword_dict

    async def get_by_id(self, dict_id: int) -> HotwordDict | None:
        """根据 ID 获取热词词典。"""
        return await self._repo.get_by_id(self._session, dict_id)

    async def get_by_name(self, name: str) -> HotwordDict | None:
        """根据名称获取热词词典。"""
        return await self._repo.get_active_by_name(self._session, name)

    async def get_all_active(self) -> list[HotwordDict]:
        """获取所有激活的热词词典。"""
        return await self._repo.get_all_active(self._session)

    async def get_all(self, offset: int = 0, limit: int = 100) -> tuple[list[HotwordDict], int]:
        """获取热词词典列表及总数。"""
        items = await self._repo.get_all(self._session, offset=offset, limit=limit)
        count_stmt = select(func.count()).select_from(HotwordDict)
        result = await self._session.execute(count_stmt)
        total = result.scalar_one()
        return items, total

    async def update(self, dict_id: int, data: HotwordDictUpdate) -> HotwordDict | None:
        """更新热词词典。"""
        update_fields = data.model_dump(exclude_unset=True)
        if not update_fields:
            return await self._repo.get_by_id(self._session, dict_id)

        if "words" in update_fields:
            update_fields["words_json"] = json.dumps(update_fields.pop("words"), ensure_ascii=False)

        try:
            hotword_dict = await self._repo.update(self._session, dict_id, **update_fields)
        except ValueError:
            return None
        await self._session.flush()
        logger.info("热词词典已更新", dict_id=dict_id, fields=list(update_fields.keys()))
        return hotword_dict

    async def delete(self, dict_id: int) -> bool:
        """删除热词词典。"""
        result = await self._repo.delete(self._session, dict_id)
        if result:
            await self._session.flush()
            logger.info("热词词典已删除", dict_id=dict_id)
        return result
