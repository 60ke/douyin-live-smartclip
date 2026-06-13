"""SQLAlchemy ORM 模型定义。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, String, func
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    MappedAsDataclass,
    mapped_column,
    relationship,
)


class Base(DeclarativeBase, MappedAsDataclass):
    """声明式基类，同时作为 dataclass 使用。"""


# ---------------------------------------------------------------------------
# 直播间
# ---------------------------------------------------------------------------


class LiveRoom(Base):
    """直播间。"""

    __tablename__ = "live_rooms"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, init=False)
    url: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    platform: Mapped[str] = mapped_column(String(64), nullable=False, default="douyin")
    quality: Mapped[str] = mapped_column(String(64), nullable=False, default="origin")
    max_duration_seconds: Mapped[int] = mapped_column(nullable=False, default=3600)
    pipeline_config_json: Mapped[str | None] = mapped_column(
        String(4096), nullable=True, default=None
    )
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), init=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), init=False
    )

    tasks: Mapped[list[Task]] = relationship(back_populates="room", init=False)


# ---------------------------------------------------------------------------
# 任务
# ---------------------------------------------------------------------------


class Task(Base):
    """录制 / 切片任务。"""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, init=False)
    room_id: Mapped[int] = mapped_column(ForeignKey("live_rooms.id"), nullable=False)
    task_type: Mapped[str] = mapped_column(String(32), nullable=False)
    cron_expression: Mapped[str | None] = mapped_column(String(128), nullable=True, default=None)
    pipeline_config_json: Mapped[str | None] = mapped_column(
        String(4096), nullable=True, default=None
    )
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), init=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), init=False
    )

    room: Mapped[LiveRoom] = relationship(back_populates="tasks", init=False)
    runs: Mapped[list[TaskRun]] = relationship(back_populates="task", init=False)


# ---------------------------------------------------------------------------
# 任务运行
# ---------------------------------------------------------------------------


class TaskRun(Base):
    """任务运行实例。"""

    __tablename__ = "task_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, init=False)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    run_status: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True, default=None)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True, default=None)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    error_message: Mapped[str | None] = mapped_column(String(2048), nullable=True, default=None)
    heartbeat_at: Mapped[datetime | None] = mapped_column(nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), init=False)

    task: Mapped[Task] = relationship(back_populates="runs", init=False)
    steps: Mapped[list[TaskStep]] = relationship(back_populates="run", init=False)
    records: Mapped[list[Record]] = relationship(back_populates="run", init=False)
    subtitles: Mapped[list[Subtitle]] = relationship(back_populates="run", init=False)
    clip_plans: Mapped[list[ClipPlan]] = relationship(back_populates="run", init=False)


# ---------------------------------------------------------------------------
# 任务步骤
# ---------------------------------------------------------------------------


class TaskStep(Base):
    """流水线步骤执行记录。"""

    __tablename__ = "task_steps"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, init=False)
    run_id: Mapped[int] = mapped_column(ForeignKey("task_runs.id"), nullable=False)
    step_name: Mapped[str] = mapped_column(String(64), nullable=False)
    step_status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True, default=None)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True, default=None)
    input_path: Mapped[str | None] = mapped_column(String(1024), nullable=True, default=None)
    output_path: Mapped[str | None] = mapped_column(String(1024), nullable=True, default=None)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    error_message: Mapped[str | None] = mapped_column(String(2048), nullable=True, default=None)
    duration_ms: Mapped[int] = mapped_column(nullable=False, default=0)
    metadata_json: Mapped[str | None] = mapped_column(String(8192), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), init=False)

    run: Mapped[TaskRun] = relationship(back_populates="steps", init=False)


# ---------------------------------------------------------------------------
# 录制产物
# ---------------------------------------------------------------------------


class Record(Base):
    """录制文件记录。"""

    __tablename__ = "records"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, init=False)
    run_id: Mapped[int] = mapped_column(ForeignKey("task_runs.id"), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_size: Mapped[int] = mapped_column(nullable=False, default=0)
    duration_seconds: Mapped[float] = mapped_column(nullable=False, default=0.0)
    format: Mapped[str] = mapped_column(String(32), nullable=False, default="ts")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), init=False)

    run: Mapped[TaskRun] = relationship(back_populates="records", init=False)


# ---------------------------------------------------------------------------
# 字幕
# ---------------------------------------------------------------------------


class Subtitle(Base):
    """字幕文件记录。"""

    __tablename__ = "subtitles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, init=False)
    run_id: Mapped[int] = mapped_column(ForeignKey("task_runs.id"), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="zh")
    word_count: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), init=False)

    run: Mapped[TaskRun] = relationship(back_populates="subtitles", init=False)


# ---------------------------------------------------------------------------
# 切片方案
# ---------------------------------------------------------------------------


class ClipPlan(Base):
    """切片方案。"""

    __tablename__ = "clip_plans"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, init=False)
    run_id: Mapped[int] = mapped_column(ForeignKey("task_runs.id"), nullable=False)
    llm_profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("llm_profiles.id"), nullable=True, default=None
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    raw_llm_response_path: Mapped[str | None] = mapped_column(
        String(1024), nullable=True, default=None
    )
    normalized_plan_path: Mapped[str | None] = mapped_column(
        String(1024), nullable=True, default=None
    )
    validated_plan_path: Mapped[str | None] = mapped_column(
        String(1024), nullable=True, default=None
    )
    segment_count: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), init=False)

    run: Mapped[TaskRun] = relationship(back_populates="clip_plans", init=False)
    llm_profile: Mapped[LlmProfile | None] = relationship(init=False)
    clips: Mapped[list[Clip]] = relationship(back_populates="plan", init=False)


# ---------------------------------------------------------------------------
# 切片
# ---------------------------------------------------------------------------


class Clip(Base):
    """单个切片。"""

    __tablename__ = "clips"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, init=False)
    plan_id: Mapped[int] = mapped_column(ForeignKey("clip_plans.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    start_subtitle_index: Mapped[int] = mapped_column(nullable=False)
    end_subtitle_index: Mapped[int] = mapped_column(nullable=False)
    parts_json: Mapped[str | None] = mapped_column(String(16384), nullable=True, default=None)
    score: Mapped[float] = mapped_column(nullable=False, default=0.0)
    structure_score: Mapped[float] = mapped_column(nullable=False, default=0.0)
    reason: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
    structure_reason: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    output_path: Mapped[str | None] = mapped_column(String(1024), nullable=True, default=None)
    subtitle_output_path: Mapped[str | None] = mapped_column(
        String(1024), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), init=False)

    plan: Mapped[ClipPlan] = relationship(back_populates="clips", init=False)


# ---------------------------------------------------------------------------
# LLM 配置
# ---------------------------------------------------------------------------


class LlmProfile(Base):
    """大模型调用配置档案。"""

    __tablename__ = "llm_profiles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, init=False)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    api_key_env: Mapped[str] = mapped_column(String(256), nullable=False, default="LLM_API_KEY")
    model: Mapped[str] = mapped_column(String(256), nullable=False, default="deepseek-v4-flash")
    base_url: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    temperature: Mapped[float] = mapped_column(nullable=False, default=0.2)
    max_tokens: Mapped[int] = mapped_column(nullable=False, default=1200)
    timeout_seconds: Mapped[int] = mapped_column(nullable=False, default=90)
    max_retries: Mapped[int] = mapped_column(nullable=False, default=4)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), init=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), init=False
    )


# ---------------------------------------------------------------------------
# Prompt 配置
# ---------------------------------------------------------------------------


class PromptProfile(Base):
    """Prompt 模板配置。"""

    __tablename__ = "prompt_profiles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, init=False)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    step_name: Mapped[str] = mapped_column(String(64), nullable=False)
    template_text: Mapped[str] = mapped_column(String(16384), nullable=False)
    description: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), init=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), init=False
    )


# ---------------------------------------------------------------------------
# 热词词典
# ---------------------------------------------------------------------------


class HotwordDict(Base):
    """热词词典。"""

    __tablename__ = "hotword_dicts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, init=False)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    words_json: Mapped[str] = mapped_column(String(65536), nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), init=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), init=False
    )
