"""FastAPI 应用工厂。"""

from __future__ import annotations

import asyncio

import structlog
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

from liveclip.api.routes import (
    clips_router,
    hotwords_router,
    live_rooms_router,
    media_router,
    prompts_router,
    recordings_router,
    runs_router,
    tasks_router,
)
from liveclip.config import AppSettings, ensure_directories, load_settings
from liveclip.db import session as db_session
from liveclip.db.models import Base
from liveclip.db.session import init_db
from liveclip.exceptions import LiveClipError

logger = structlog.get_logger(__name__)


def create_app(settings: AppSettings | None = None) -> FastAPI:
    """创建并配置 FastAPI 应用实例。"""
    load_dotenv()  # 加载 .env 文件中的环境变量（DOUYIN_COOKIE 等）
    if settings is None:
        settings = load_settings()

    app = FastAPI(
        title="LiveClip API",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # ---- CORS ----
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---- 路由注册 ----
    app.include_router(live_rooms_router)
    app.include_router(tasks_router)
    app.include_router(runs_router)
    app.include_router(clips_router)
    app.include_router(media_router)
    app.include_router(recordings_router)
    app.include_router(prompts_router)
    app.include_router(hotwords_router)

    # ---- 异常处理 ----
    @app.exception_handler(LiveClipError)
    async def liveclip_error_handler(request: Request, exc: LiveClipError) -> JSONResponse:
        """将 LiveClipError 转换为结构化 JSON 响应。"""
        logger.warning(
            "LiveClipError",
            error_code=exc.error_code,
            message=exc.message,
            path=request.url.path,
        )
        return JSONResponse(
            status_code=400,
            content={
                "error_code": exc.error_code,
                "message": exc.message,
                "details": exc.details,
            },
        )

    # ---- 健康检查 ----
    @app.get("/health", tags=["health"])
    async def health_check() -> dict[str, str]:
        """服务健康检查端点。"""
        return {"status": "ok"}

    # ---- 启动事件 ----
    @app.on_event("startup")
    async def on_startup() -> None:
        """应用启动时初始化数据库和目录。"""
        init_db(settings.database.url)
        if db_session.engine is None:
            raise RuntimeError("数据库未初始化，请先调用 init_db()")
        async with db_session.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(_ensure_productized_clip_columns)
        ensure_directories(settings)
        logger.info("应用启动完成", database_url=settings.database.url)
        if settings.worker.auto_start_with_api:
            await _start_embedded_worker(app, settings)

    @app.on_event("shutdown")
    async def on_shutdown() -> None:
        """应用关闭时停止内置 worker。"""
        await _stop_embedded_worker(app, settings)

    return app


def _ensure_productized_clip_columns(connection: Connection) -> None:
    """补齐早期 MVP 数据库缺失的切片映射字段。"""
    inspector = inspect(connection)
    table_names = set(inspector.get_table_names())
    if "clips" not in table_names:
        return

    existing = {column["name"] for column in inspector.get_columns("clips")}
    columns = {
        "source_record_id": "ALTER TABLE clips ADD COLUMN source_record_id INT NULL",
        "start_seconds": "ALTER TABLE clips ADD COLUMN start_seconds DOUBLE NULL",
        "end_seconds": "ALTER TABLE clips ADD COLUMN end_seconds DOUBLE NULL",
        "duration_seconds": "ALTER TABLE clips ADD COLUMN duration_seconds DOUBLE NULL",
    }
    for name, ddl in columns.items():
        if name not in existing:
            connection.execute(text(ddl))


async def _start_embedded_worker(app: FastAPI, settings: AppSettings) -> None:
    """在 API 进程内启动后台 worker，用于本地和 MVP 一体化部署。"""
    if getattr(app.state, "liveclip_worker_task", None) is not None:
        return

    from liveclip.worker.runner import WorkerRunner

    runner = WorkerRunner(settings)
    task = asyncio.create_task(runner.run(), name="liveclip-embedded-worker")
    app.state.liveclip_worker_runner = runner
    app.state.liveclip_worker_task = task
    logger.info(
        "内置 worker 已启动",
        poll_interval=settings.worker.poll_interval_seconds,
    )


async def _stop_embedded_worker(app: FastAPI, settings: AppSettings) -> None:
    """停止 API 进程内的后台 worker（立即取消，不等待）。"""
    runner = getattr(app.state, "liveclip_worker_runner", None)
    task = getattr(app.state, "liveclip_worker_task", None)
    if runner is None or task is None:
        return

    runner.shutdown()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    app.state.liveclip_worker_runner = None
    app.state.liveclip_worker_task = None
    logger.info("内置 worker 已停止")
