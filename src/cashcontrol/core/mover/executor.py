"""
executor.py — Async Mover execution engine.

Runs scenario steps sequentially, reports progress, determines touch subtype,
and collects results.

Usage:
    executor = MoverExecutor(session, scenario, params)
    result = await executor.run(progress_callback)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from cashcontrol.core.mover.steps import STEP_REGISTRY
from cashcontrol.core.mover.steps.base import (
    BaseStep,
    ExecutionContext,
    StepResult,
)
from cashcontrol.infrastructure.audit_logger import audit_log, get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from cashcontrol.core.mover.scenario import Scenario, StepDefinition
    from cashcontrol.core.session import CashSession

logger = get_logger()


@dataclass
class StepReport:
    """Report for a single executed step."""

    step_def: StepDefinition
    result: StepResult
    skipped: bool = False
    skip_reason: str = ""


@dataclass
class ExecutionReport:
    """Complete report for a Mover scenario execution."""

    scenario_name: str
    cash_type: str
    host: str
    touch_subtype: str = ""
    steps: list[StepReport] = field(default_factory=list)
    success: bool = True
    error: str | None = None

    @property
    def total_steps(self) -> int:
        return len(self.steps)

    @property
    def executed_steps(self) -> int:
        return sum(1 for s in self.steps if not s.skipped)

    @property
    def successful_steps(self) -> int:
        return sum(1 for s in self.steps if not s.skipped and s.result.success)

    @property
    def failed_steps(self) -> int:
        return sum(
            1 for s in self.steps if not s.skipped and not s.result.success
        )

    @property
    def skipped_steps(self) -> int:
        return sum(1 for s in self.steps if s.skipped)


@dataclass
class MoverParams:
    """Parameters provided by user before execution."""

    com_port: str = ""  # COM port for bank terminal (POS only)
    shop_name: str = ""  # e.g. "КЯ-3" — manual override if DB is empty
    cash_number: str = ""  # e.g. "1" — manual override if DB is empty


class MoverExecutor:
    """
    Async Mover execution engine.

    Runs scenario steps on a connected cash session, detects touch subtype
    automatically, and reports progress.
    """

    def __init__(
        self,
        session: CashSession,
        scenario: Scenario,
        params: MoverParams | None = None,
    ) -> None:
        self._session = session
        self._scenario = scenario
        self._params = params or MoverParams()

    async def run(
        self,
        progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> ExecutionReport:
        """
        Execute the scenario on the connected session.
        """
        cash_type, report = await self._setup(progress)
        if not cash_type:
            return report

        shop_name, cash_number = await self._resolve_shop_info(progress)

        ctx = await self._detect_touch_and_build_context(
            cash_type, shop_name, cash_number, progress, report,
        )

        steps = self._scenario.get_steps_for_cash_type(cash_type)
        total = len(steps)

        if total == 0:
            if progress:
                await progress(f"Нет шагов для типа кассы '{cash_type}' в сценарии")
            return report

        await self._log_start(progress, cash_type, total)
        await self._execute_steps(report, steps, total, ctx, progress)
        await self._finalize(report, progress)

        return report

    async def _setup(
        self,
        progress: Callable[[str], Awaitable[None]] | None,
    ) -> tuple[str | None, ExecutionReport]:
        cash_type = getattr(self._session, "cash_type", None) or "unknown"
        report = ExecutionReport(
            scenario_name=self._scenario.name,
            cash_type=cash_type,
            host=self._session.host,
        )
        if cash_type == "unknown":
            report.success = False
            report.error = "Тип кассы не определён"
            return None, report
        return cash_type, report

    async def _resolve_shop_info(
        self,
        progress: Callable[[str], Awaitable[None]] | None,
    ) -> tuple[str, str]:
        shop_name, cash_number = await self._get_shop_info(progress)
        if not shop_name and self._params.shop_name:
            shop_name = self._params.shop_name
            if progress:
                await progress(f"Магазин (ручной ввод): {shop_name}")
        if not cash_number and self._params.cash_number:
            cash_number = self._params.cash_number
            if progress:
                await progress(f"Касса (ручной ввод): {cash_number}")
        return shop_name, cash_number

    async def _detect_touch_and_build_context(
        self,
        cash_type: str,
        shop_name: str,
        cash_number: str,
        progress: Callable[[str], Awaitable[None]] | None,
        report: ExecutionReport,
    ) -> ExecutionContext:
        touch_subtype = ""
        if cash_type == "touch":
            if progress:
                await progress("Определение подтипа touch-кассы...")
            touch_subtype = await self._detect_touch_subtype()
            report.touch_subtype = touch_subtype
            if progress:
                await progress(f"  Подтип: {touch_subtype or 'не определён'}")
        return ExecutionContext(
            session=self._session,
            cash_type=cash_type,
            touch_subtype=touch_subtype,
            shop_name=shop_name,
            cash_number=cash_number,
            com_port=self._params.com_port,
            progress=progress,
        )

    async def _log_start(
        self,
        progress: Callable[[str], Awaitable[None]] | None,
        cash_type: str,
        total: int,
    ) -> None:
        if progress:
            await progress(
                f"Запуск сценария «{self._scenario.name}» "
                f"({total} шагов для {cash_type})"
            )
        audit_log(
            "mover", "mover_start", "success",
            target=self._session.host,
            scenario=self._scenario.name,
            cash_type=cash_type,
            steps=total,
        )

    async def _execute_steps(
        self,
        report: ExecutionReport,
        steps: list[StepDefinition],
        total: int,
        ctx: ExecutionContext,
        progress: Callable[[str], Awaitable[None]] | None,
    ) -> None:
        for i, step_def in enumerate(steps, 1):
            step_report = StepReport(
                step_def=step_def,
                result=StepResult(success=True),
            )

            step_cls = STEP_REGISTRY.get(step_def.type)
            if step_cls is None:
                step_report.skipped = True
                step_report.skip_reason = f"Неизвестный тип шага: {step_def.type}"
                report.steps.append(step_report)
                if progress:
                    await progress(
                        f"⏭ [{i}/{total}] {step_def.label}: пропущен "
                        f"(неизвестный тип)"
                    )
                continue

            if progress:
                await progress(f"▶ [{i}/{total}] {step_def.label}...")

            try:
                step_instance: BaseStep = step_cls()
                result = await step_instance.execute(step_def, ctx)
                step_report.result = result

                if not result.success:
                    report.success = False

                icon = "✅" if result.success else "❌"
                if progress:
                    await progress(
                        f"{icon} [{i}/{total}] {step_def.label}: "
                        f"{result.message}"
                    )

            except Exception as e:
                logger.exception(f"Step '{step_def.label}' failed with exception")
                step_report.result = StepResult(
                    success=False,
                    message=f"Исключение: {e}",
                )
                report.success = False

                if progress:
                    await progress(
                        f"❌ [{i}/{total}] {step_def.label}: Исключение: {e}"
                    )

            report.steps.append(step_report)

    async def _finalize(
        self,
        report: ExecutionReport,
        progress: Callable[[str], Awaitable[None]] | None,
    ) -> None:
        if progress:
            status = "✅ Завершено" if report.success else "⚠ Завершено с ошибками"
            await progress(
                f"\n{status}: "
                f"{report.successful_steps}/{report.executed_steps} успешно"
                + (f", {report.skipped_steps} пропущено"
                   if report.skipped_steps else "")
            )
        audit_log(
            "mover",
            "mover_complete",
            "success" if report.success else "error",
            target=self._session.host,
            scenario=self._scenario.name,
            executed=report.executed_steps,
            successful=report.successful_steps,
            failed=report.failed_steps,
        )

    async def _get_shop_info(
        self,
        progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> tuple[str, str]:
        """
        Get shop name and cash number from catalog DB.

        Creates a temporary connection to the 'catalog' database
        (the main session may be connected to a different DB or not at all).

        Returns:
            (shop_name, cash_number) e.g. ("КЯ-3", "1")
        """
        shop_name = ""
        cash_number = ""

        try:
            from cashcontrol.core.db import DBSession

            db = DBSession(self._session.host, database="catalog")
            try:
                await db.connect()
            except Exception as e:
                logger.warning(f"Cannot connect to catalog DB on {self._session.host}: {e}")
                if progress:
                    await progress(f"⚠ Нет подключения к БД catalog: {e}")
                return (shop_name, cash_number)

            try:
                # Query shop name
                rows = await db.execute(
                    "SELECT property_value FROM public.sales_management_properties "
                    "WHERE property_key = 'shopName' LIMIT 1;"
                )
                if rows and rows[0]:
                    shop_name = str(rows[0][0]).strip()

                # Query cash number
                rows = await db.execute(
                    "SELECT property_value FROM public.sales_management_properties "
                    "WHERE property_key = 'cashNumber' LIMIT 1;"
                )
                if rows and rows[0]:
                    cash_number = str(rows[0][0]).strip()

                if progress and shop_name:
                    await progress(
                        f"Магазин: {shop_name}, касса: {cash_number}"
                    )
            finally:
                await db.disconnect()

        except Exception as e:
            logger.warning(f"Failed to get shop info from DB: {e}")
            if progress:
                await progress(f"⚠ Не удалось получить данные магазина: {e}")

        return (shop_name, cash_number)

    async def _detect_touch_subtype(self) -> str:
        """
        Detect touch cash subtype: screen form + brand.

        Screen form: 'wide' or 'quad' (from xrandr resolution)
        Brand: 'kya' or 'baton' (from shopName prefix in catalog DB)

        Returns:
            Subtype string like 'wide-kya', 'quad-baton', etc.
            Returns empty string if detection fails.
        """
        screen_form = "wide"  # default
        brand = "unknown"

        # 1. Detect brand from shopName (via temporary catalog DB connection)
        try:
            from cashcontrol.core.db import DBSession

            db = DBSession(self._session.host, database="catalog")
            try:
                await db.connect()
                rows = await db.execute(
                    "SELECT property_value FROM public.sales_management_properties "
                    "WHERE property_key = 'shopName' LIMIT 1;"
                )
                if rows and rows[0]:
                    shop_name = str(rows[0][0]).strip().lower()
                    if shop_name.startswith("кя-"):
                        brand = "kya"
                    elif shop_name.startswith("д-"):
                        brand = "baton"
            except Exception as e:
                logger.warning(f"Failed to detect touch brand from DB: {e}")
            finally:
                await db.disconnect()
        except Exception as e:
            logger.warning(f"Failed to detect touch brand: {e}")

        # 2. Detect screen form from xrandr
        try:
            xrandr_result = await self._session.ssh.execute(
                "export DISPLAY=:0 && xrandr"
            )
            if xrandr_result.success and xrandr_result.stdout:
                for line in xrandr_result.stdout.splitlines():
                    if "connected primary" in line:
                        screen_form = "quad" if "1024x768" in line else "wide"
                        break
        except Exception as e:
            logger.warning(f"Failed to detect screen form: {e}")

        subtype = f"{screen_form}-{brand}"
        logger.info(
            f"Touch subtype for {self._session.host}: {subtype}"
        )
        return subtype