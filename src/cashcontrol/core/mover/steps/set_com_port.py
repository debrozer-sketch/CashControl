"""
set_com_port.py — Set COM port for bank terminal in pinpad.ini.

Updates the ComPort= line in pinpad.ini on the cash register.
COM port value is provided by the user before execution.

Config format:
    {
        "target_path": "/home/tc/storage/crystal-cash/banks/sberbank/linux/pinpad.ini"
    }
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cashcontrol.core.mover.steps.base import BaseStep, ExecutionContext, StepResult
from cashcontrol.infrastructure.audit_logger import get_logger

if TYPE_CHECKING:
    from cashcontrol.core.mover.scenario import StepDefinition

logger = get_logger()

DEFAULT_TARGET_PATH = (
    "/home/tc/storage/crystal-cash/banks/sberbank/linux/pinpad.ini"
)


class SetComPortStep(BaseStep):
    """Update COM port in pinpad.ini on the cash register."""

    async def execute(
        self,
        step_def: StepDefinition,
        ctx: ExecutionContext,
    ) -> StepResult:
        config = step_def.config
        target_path = config.get("target_path", DEFAULT_TARGET_PATH)

        com_port = ctx.com_port.strip()
        if not com_port:
            return StepResult(
                success=False,
                message="COM-порт не указан",
            )

        if not com_port.isdigit():
            return StepResult(
                success=False,
                message=f"COM-порт должен быть числом, получено: '{com_port}'",
            )

        await ctx.log(f"Установка COM-порта: {com_port}")

        sed_cmd = (
            f"sed -i 's/^ComPort=.*/ComPort={com_port}/' "
            f"'{target_path}'"
        )

        try:
            cmd_result = await ctx.session.ssh.execute(sed_cmd)
            if not cmd_result.success:
                return StepResult(
                    success=False,
                    message=f"Ошибка sed: {cmd_result.stderr[:200]}",
                )
        except Exception as e:
            return StepResult(success=False, message=f"Ошибка SSH: {e}")

        return StepResult(
            success=True,
            message=f"COM-порт установлен: {com_port}",
            data={"com_port": com_port},
        )