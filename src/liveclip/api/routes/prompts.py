"""Prompt 配置 CRUD 路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from liveclip.api.deps import get_db_session, get_prompt_service
from liveclip.schemas.prompt import (
    PromptProfileCreate,
    PromptProfileResponse,
    PromptProfileUpdate,
)
from liveclip.services import PromptService

router = APIRouter(prefix="/api/v1/prompts", tags=["prompts"])


@router.post("/", response_model=PromptProfileResponse, status_code=status.HTTP_201_CREATED)
async def create_prompt_profile(
    body: PromptProfileCreate,
    session: AsyncSession = Depends(get_db_session),
    service: PromptService = Depends(get_prompt_service),
) -> PromptProfileResponse:
    """创建 Prompt 配置。"""
    profile = await service.create(body)
    await session.commit()
    return PromptProfileResponse.model_validate(profile)


@router.get("/", response_model=list[PromptProfileResponse])
async def list_prompt_profiles(
    offset: int = 0,
    limit: int = 100,
    session: AsyncSession = Depends(get_db_session),
    service: PromptService = Depends(get_prompt_service),
) -> list[PromptProfileResponse]:
    """获取 Prompt 配置列表。"""
    items, _total = await service.get_all(offset=offset, limit=limit)
    await session.commit()
    return [PromptProfileResponse.model_validate(p) for p in items]


@router.get("/{profile_id}", response_model=PromptProfileResponse)
async def get_prompt_profile(
    profile_id: int,
    session: AsyncSession = Depends(get_db_session),
    service: PromptService = Depends(get_prompt_service),
) -> PromptProfileResponse:
    """获取单个 Prompt 配置。"""
    profile = await service.get_by_id(profile_id)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt 配置不存在")
    await session.commit()
    return PromptProfileResponse.model_validate(profile)


@router.put("/{profile_id}", response_model=PromptProfileResponse)
async def update_prompt_profile(
    profile_id: int,
    body: PromptProfileUpdate,
    session: AsyncSession = Depends(get_db_session),
    service: PromptService = Depends(get_prompt_service),
) -> PromptProfileResponse:
    """更新 Prompt 配置。"""
    profile = await service.update(profile_id, body)
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt 配置不存在")
    await session.commit()
    return PromptProfileResponse.model_validate(profile)


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_prompt_profile(
    profile_id: int,
    session: AsyncSession = Depends(get_db_session),
    service: PromptService = Depends(get_prompt_service),
) -> None:
    """删除 Prompt 配置。"""
    deleted = await service.delete(profile_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt 配置不存在")
    await session.commit()
