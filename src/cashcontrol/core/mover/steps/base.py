"""
base.py — Base class for all Mover step implementations.

Each step receives a CashSession, step configuration, and execution parameters,
and produces a StepResult with success/failure status and messages.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cashcontrol.core.mover.scenario import StepDefinition
    from cashcontrol.core.session import CashSession


@dataclass
class StepResult:
    """Result of executing a single Mover step."""

    success: bool
    message: str = ""
    details: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)

    def add_detail(self, text: str) -> None:
        """Add a detail line to the result."""
        self.details.append(text)


# Type alias for progress callback: (message: str) -> None
ProgressCallback = Callable[[str], Awaitable[None]]


@dataclass
class ExecutionContext:
    """
    Shared context passed to all steps during execution.

    Contains session, cash type, shop info, and user-provided parameters.
    """

    session: CashSession
    cash_type: str  # "pos", "touch", "sco3"
    touch_subtype: str = ""  # "wide-kya", "quad-baton", etc. (only for touch)
    shop_name: str = ""  # e.g. "КЯ-3", "Д-15"
    cash_number: str = ""  # e.g. "1", "22"
    com_port: str = ""  # e.g. "3" (user input, POS only)
    progress: ProgressCallback | None = None

    @property
    def precise_cash_type(self) -> str:
        """
        Get precise cash type for command selection.

        For touch: returns 'touch-{screen}-{brand}' (e.g. 'touch-wide-kya')
        For others: returns base type (e.g. 'pos', 'sco3')
        """
        if self.cash_type == "touch" and self.touch_subtype:
            return f"touch-{self.touch_subtype}"
        return self.cash_type

    async def log(self, message: str) -> None:
        """Send progress message to callback if available."""
        if self.progress:
            await self.progress(message)


class BaseStep:
    """
    Abstract base class for Mover step implementations.

    Subclasses must implement execute().
    """

    async def execute(
        self,
        step_def: StepDefinition,
        ctx: ExecutionContext,
    ) -> StepResult:
        """
        Execute this step.

        Args:
            step_def: Step definition with configuration.
            ctx: Execution context with session, cash type, parameters.

        Returns:
            StepResult with success/failure and messages.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement execute()"
        )