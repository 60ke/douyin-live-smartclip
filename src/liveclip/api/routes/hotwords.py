"""热词词典 CRUD 路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from liveclip.api.deps import get_db_session, get_hotword_service
from liveclip.schemas.hotword import (
    HotwordDictCreate,
    HotwordDictResponse,
    HotwordDictUpdate,
)
from liveclip.services import HotwordService

router = APIRouter(prefix="/api/v1/hotwords", tags=["hotwords"])


@router.post("/", response_model=HotwordDictResponse, status_code=status.HTTP_201_CREATED)
async def create_hotword_dict(
    body: HotwordDictCreate,
    session: AsyncSession = Depends(get_db_session),
    service: HotwordService = Depends(get_hotword_service),
) -> HotwordDictResponse:
    """创建热词词典。"""
    hotword_dict = await service.create(body)
    await session.commit()
    return HotwordDictResponse.model_validate(hotword_dict)


@router.get("/", response_model=list[HotwordDictResponse])
async def list_hotword_dicts(
    offset: int = 0,
    limit: int = 100,
    session: AsyncSession = Depends(get_db_session),
    service: HotwordService = Depends(get_hotword_service),
) -> list[HotwordDictResponse]:
    """获取热词词典列表。"""
    items, _total = await service.get_all(offset=offset, limit=limit)
    await session.commit()
    return [HotwordDictResponse.model_validate(d) for d in items]


@router.get("/{dict_id}", response_model=HotwordDictResponse)
async def get_hotword_dict(
    dict_id: int,
    session: AsyncSession = Depends(get_db_session),
    service: HotwordService = Depends(get_hotword_service),
) -> HotwordDictResponse:
    """获取单个热词词典。"""
    hotword_dict = await service.get_by_id(dict_id)
    if hotword_dict is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="热词词典不存在")
    await session.commit()
    return HotwordDictResponse.model_validate(hotword_dict)


@router.put("/{dict_id}", response_model=HotwordDictResponse)
async def update_hotword_dict(
    dict_id: int,
    body: HotwordDictUpdate,
    session: AsyncSession = Depends(get_db_session),
    service: HotwordService = Depends(get_hotword_service),
) -> HotwordDictResponse:
    """更新热词词典。"""
    hotword_dict = await service.update(dict_id, body)
    if hotword_dict is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="热词词典不存在")
    await session.commit()
    return HotwordDictResponse.model_validate(hotword_dict)


@router.delete("/{dict_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_hotword_dict(
    dict_id: int,
    session: AsyncSession = Depends(get_db_session),
    service: HotwordService = Depends(get_hotword_service),
) -> None:
    """删除热词词典。"""
    deleted = await service.delete(dict_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="热词词典不存在")
    await session.commit()
