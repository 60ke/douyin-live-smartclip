"""运行管理路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from liveclip.api.deps import get_db_session, get_run_service
from liveclip.domain.enums import RunStatus
from liveclip.schemas.run import RunDetailResponse, RunListResponse, RunResponse, StepResponse
from liveclip.services import RunService
from liveclip.utils.timezone import as_china_aware

router = APIRouter(prefix="/api/v1/runs", tags=["runs"])


def _apply_tz(run_response: RunResponse) -> RunResponse:
    """将 RunResponse 中的 datetime 字段转换为东八区带时区时间。"""
    data = run_response.model_dump()
    _apply_run_tz(data)
    return RunResponse(**data)


def _apply_run_tz(data: dict[str, object]) -> None:
    reference = data.get("created_at")
    for key in ("started_at", "finished_at", "heartbeat_at"):
        if key in data and data[key] is not None:
            data[key] = as_china_aware(data[key], reference=reference)  # type: ignore[arg-type]
    if data.get("created_at") is not None:
        data["created_at"] = as_china_aware(data["created_at"])  # type: ignore[arg-type]


def _apply_step_tz(step_response: StepResponse) -> StepResponse:
    data = step_response.model_dump()
    reference = data.get("created_at")
    for key in ("started_at", "finished_at"):
        if key in data and data[key] is not None:
            data[key] = as_china_aware(data[key], reference=reference)  # type: ignore[arg-type]
    if data.get("created_at") is not None:
        data["created_at"] = as_china_aware(data["created_at"])  # type: ignore[arg-type]
    return StepResponse(**data)


@router.get("/", response_model=RunListResponse)
async def list_runs(
    offset: int = 0,
    limit: int = 100,
    session: AsyncSession = Depends(get_db_session),
    service: RunService = Depends(get_run_service),
) -> RunListResponse:
    """获取运行列表。"""
    items, total = await service.get_all(offset=offset, limit=limit)
    response = RunListResponse(
        items=[_apply_tz(RunResponse.model_validate(r)) for r in items],
        total=total,
    )
    await session.commit()
    return response


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
    run_data = RunResponse.model_validate(run).model_dump()
    _apply_run_tz(run_data)
    response = RunDetailResponse(
        **run_data,
        steps=[_apply_step_tz(StepResponse.model_validate(s)) for s in steps],
    )
    await session.commit()
    return response


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
    run = await service.get_by_id(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="运行不存在") from None
    await session.flush()
    await session.refresh(run)
    response = _apply_tz(RunResponse.model_validate(run))
    await session.commit()
    return response
