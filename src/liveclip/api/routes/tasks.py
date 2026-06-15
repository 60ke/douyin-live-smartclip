"""任务 CRUD + 运行触发路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from liveclip.api.deps import get_db_session, get_run_service, get_task_service
from liveclip.domain.enums import TriggerType
from liveclip.schemas.run import RunCreate, RunListResponse, RunResponse
from liveclip.schemas.task import (
    TaskCreate,
    TaskListResponse,
    TaskResponse,
    TaskUpdate,
)
from liveclip.services import RunService, TaskService

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


@router.post("/", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    body: TaskCreate,
    session: AsyncSession = Depends(get_db_session),
    service: TaskService = Depends(get_task_service),
) -> TaskResponse:
    """创建任务。"""
    task = await service.create(body)
    response = TaskResponse.model_validate(task)
    await session.commit()
    return response


@router.get("/", response_model=TaskListResponse)
async def list_tasks(
    offset: int = 0,
    limit: int = 100,
    session: AsyncSession = Depends(get_db_session),
    service: TaskService = Depends(get_task_service),
) -> TaskListResponse:
    """获取任务列表。"""
    items, total = await service.get_all(offset=offset, limit=limit)
    response = TaskListResponse(
        items=[TaskResponse.model_validate(t) for t in items],
        total=total,
    )
    await session.commit()
    return response


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: int,
    session: AsyncSession = Depends(get_db_session),
    service: TaskService = Depends(get_task_service),
) -> TaskResponse:
    """获取单个任务。"""
    task = await service.get_by_id(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    response = TaskResponse.model_validate(task)
    await session.commit()
    return response


@router.put("/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: int,
    body: TaskUpdate,
    session: AsyncSession = Depends(get_db_session),
    service: TaskService = Depends(get_task_service),
) -> TaskResponse:
    """更新任务。"""
    task = await service.update(task_id, body)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    response = TaskResponse.model_validate(task)
    await session.commit()
    return response


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: int,
    session: AsyncSession = Depends(get_db_session),
    service: TaskService = Depends(get_task_service),
) -> None:
    """删除任务。"""
    deleted = await service.delete(task_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    await session.commit()


@router.post(
    "/{task_id}/runs",
    response_model=RunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def trigger_run(
    task_id: int,
    session: AsyncSession = Depends(get_db_session),
    task_service: TaskService = Depends(get_task_service),
    run_service: RunService = Depends(get_run_service),
) -> RunResponse:
    """为指定任务触发一次新运行。"""
    task = await task_service.get_by_id(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    run_create = RunCreate(task_id=task_id, trigger_type=TriggerType.API)
    run = await run_service.create(run_create)
    response = RunResponse.model_validate(run)
    await session.commit()
    return response


@router.get("/{task_id}/runs", response_model=RunListResponse)
async def list_task_runs(
    task_id: int,
    offset: int = 0,
    limit: int = 100,
    session: AsyncSession = Depends(get_db_session),
    task_service: TaskService = Depends(get_task_service),
    run_service: RunService = Depends(get_run_service),
) -> RunListResponse:
    """获取指定任务的运行列表。"""
    task = await task_service.get_by_id(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    items, total = await run_service.get_by_task(task_id, offset=offset, limit=limit)
    response = RunListResponse(
        items=[RunResponse.model_validate(r) for r in items],
        total=total,
    )
    await session.commit()
    return response
