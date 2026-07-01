"""导出服务 — 为外部同步消费端提供已完成切片的游标分页查询。"""

from __future__ import annotations

from urllib.parse import quote

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from liveclip.db.models import Clip, ClipPlan, LiveRoom, Task, TaskRun
from liveclip.schemas.export import ExportClipItem, ExportClipsResponse, ExportCursor


def build_media_url(path: str | None) -> str | None:
    """Build a media URL with a safely encoded path query parameter."""
    if not path:
        return None
    return f"/api/v1/media/?path={quote(path, safe='/')}"


async def list_completed_clips(
    session: AsyncSession,
    cursor: ExportCursor | None = None,
    limit: int = 50,
) -> ExportClipsResponse:
    """返回已完成的切片，按 created_at ASC / id ASC 游标分页。

    只返回满足以下条件的切片：
    - status = 'COMPLETED'
    - 至少有一个可播放视频（output_path 或 final_video_path 非空）
    - 所属 run 的资源未被清理（resource_status != 'CLEANED'）
    - playable_video_path 优先取 final_video_path（后处理成品），无则取 output_path（原始导出）
    """
    base_conditions = [
        Clip.status == "COMPLETED",
        TaskRun.resource_status != "CLEANED",
        or_(
            Clip.output_path.is_not(None),
            Clip.final_video_path.is_not(None),
        ),
    ]

    if cursor is not None:
        base_conditions.append(
            or_(
                Clip.created_at > cursor.created_at,
                and_(
                    Clip.created_at == cursor.created_at,
                    Clip.id > cursor.id,
                ),
            )
        )

    stmt = (
        select(
            Clip.id,
            Clip.title,
            Clip.output_path,
            Clip.final_video_path,
            Clip.duration_seconds,
            Clip.created_at,
            LiveRoom.name.label("room_name"),
        )
        .join(ClipPlan, Clip.plan_id == ClipPlan.id)
        .join(TaskRun, ClipPlan.run_id == TaskRun.id)
        .join(Task, TaskRun.task_id == Task.id)
        .join(LiveRoom, Task.room_id == LiveRoom.id)
        .where(and_(*base_conditions))
        .order_by(Clip.created_at.asc(), Clip.id.asc())
        .limit(limit + 1)  # 多取一条判断是否有下一页
    )

    result = await session.execute(stmt)
    rows = result.all()

    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]

    items: list[ExportClipItem] = []
    for row in rows:
        playable = row.final_video_path or row.output_path
        items.append(
            ExportClipItem(
                id=row.id,
                title=row.title,
                playable_video_path=playable,
                media_url=build_media_url(playable),
                duration_seconds=row.duration_seconds,
                room_name=row.room_name,
                created_at=row.created_at,
            )
        )

    next_cursor: str | None = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = ExportCursor(created_at=last.created_at, id=last.id).encode()

    return ExportClipsResponse(items=items, next_cursor=next_cursor, count=len(items))
