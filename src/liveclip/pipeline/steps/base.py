"""流水线步骤基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod

from liveclip.domain.enums import StepName
from liveclip.domain.models import StepResult
from liveclip.exceptions import RUN_CANCELED, WorkerError
from liveclip.observability import get_logger
from liveclip.pipeline.context import PipelineContext

logger = get_logger(__name__)


class BaseStep(ABC):
    """流水线步骤的抽象基类。

    子类必须实现 ``name`` 属性和 ``execute`` 方法。
    """

    @property
    @abstractmethod
    def name(self) -> StepName:
        """步骤名称枚举值。"""

    @abstractmethod
    def execute(self, ctx: PipelineContext) -> StepResult:
        """执行步骤逻辑。

        Args:
            ctx: 流水线执行上下文。

        Returns:
            步骤执行结果。
        """

    def _check_cancelled(self, ctx: PipelineContext) -> None:
        """检查是否已请求取消，若已取消则抛出 WorkerError。

        Args:
            ctx: 流水线执行上下文。

        Raises:
            WorkerError: 当取消已请求时。
        """
        if ctx.is_cancelled():
            logger.info("step_cancelled", step=self.name, run_id=ctx.run_id)
            raise WorkerError(
                RUN_CANCELED,
                f"步骤 {self.name} 被取消",
                details={"step": str(self.name), "run_id": ctx.run_id},
            )
