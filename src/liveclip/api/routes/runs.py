"""运行管理路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from liveclip.api.deps import get_db_session, get_run_service
from liveclip.domain.enums import RunStatus
from liveclip.schemas.run import RunDetailResponse, RunListResponse, RunResponse, StepResponse
from liveclip.services import RunService

router = APIRouter(prefix="/api/v1/runs", tags=["runs"])


@router.get("/", response_model=RunListResponse)
async def list_runs(
    offset: int = 0,
    limit: int = 100,
    session: AsyncSession = Depends(get_db_session),
    service: RunService = Depends(get_run_service),
) -> RunListResponse:
    """获取运行列表。"""
    items, total = await service.get_all(offset=offset, limit=limit)
    await session.commit()
    return RunListResponse(
        items=[RunResponse.model_validate(r) for r in items],
        total=total,
    )


@router.get("/{run_id}", response_model=RunDetailResponse)
async def get_run(
    run_id: int,
    session: AsyncSession = Depends(get_db_session),
    service: RunService = Depends(get_run_service),
) -> RunDetailResponse:
    """获取运行详情（含步骤列表）。"""
    try:
        run, steps = await service.get_detail(run_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="运行不存在") from None
    await session.commit()
    return RunDetailResponse(
        **RunResponse.model_validate(run).model_dump(),
        steps=[StepResponse.model_validate(s) for s in steps],
    )


@router.post("/{run_id}/cancel", response_model=RunResponse)
async def cancel_run(
    run_id: int,
    session: AsyncSession = Depends(get_db_session),
    service: RunService = Depends(get_run_service),
) -> RunResponse:
    """取消运行。"""
    run = await service.get_by_id(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="运行不存在") from None
    if str(run.run_status) not in (
        str(RunStatus.PENDING),
        str(RunStatus.RUNNING),
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="只有 PENDING 或 RUNNING 状态的运行才能取消",
        )
    await service.cancel_run(run_id)
    await session.commit()
    run = await service.get_by_id(run_id)
    return RunResponse.model_validate(run)
