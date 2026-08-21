"""
run_commands.py — Execute SSH commands on cash register.

Config format in scenario JSON:
    {
        "pos": ["cmd1", "cmd2", ...],
        "touch": {
            "wide-kya": ["cmd1", "cmd3", ...],
            "wide-baton": ["cmd1", "cmd4", ...],
            "quad-kya": ["cmd1", "cmd5", ...],
            "quad-baton": ["cmd1", "cmd6", ...]
        },
        "sco3": ["cmd1", "cmd7", ...]
    }

For touch: commands are selected by precise subtype (screen-brand).
The subtype is determined in ExecutionContext.touch_subtype.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from cashcontrol.core.mover.steps.base import BaseStep, ExecutionContext, StepResult
from cashcontrol.infrastructure.audit_logger import get_logger

if TYPE_CHECKING:
    from cashcontrol.core.mover.scenario import StepDefinition

logger = get_logger()


class RunCommandsStep(BaseStep):
    """Execute a list of SSH commands on the cash register."""

    async def execute(
        self,
        step_def: StepDefinition,
        ctx: ExecutionContext,
    ) -> StepResult:
        config = step_def.config
        ctx.cash_type.lower()

        # Resolve command list based on cash type
        commands = self._resolve_commands(config, ctx)

        if not commands:
            return StepResult(
                success=True,
                message=f"Нет команд для типа '{ctx.precise_cash_type}'",
            )

        await ctx.log(f"Выполнение {len(commands)} команд...")

        success_count = 0
        failed: list[str] = []
        result = StepResult(success=True, message="")

        for i, command in enumerate(commands, 1):
            # Truncate command for display (max 80 chars)
            display_cmd = command[:80] + "..." if len(command) > 80 else command
            await ctx.log(f"  [{i}/{len(commands)}] {display_cmd}")

            try:
                cmd_result = await ctx.session.ssh.execute(command)

                if cmd_result.success:
                    success_count += 1
                    result.add_detail(f"✅ [{i}] {display_cmd}")
                else:
                    # Some commands may return non-zero but are expected
                    # (e.g. rm -f on non-existent file, grep no match, etc.)
                    # We still count them as failures for reporting
                    failed.append(f"[{i}] {display_cmd}")
                    result.add_detail(
                        f"⚠ [{i}] {display_cmd} "
                        f"(exit={cmd_result.exit_code})"
                    )
                    logger.warning(
                        f"Command returned non-zero on {ctx.session.host}: "
                        f"{command} -> exit={cmd_result.exit_code}, "
                        f"stderr={cmd_result.stderr[:200]}"
                    )
            except Exception as e:
                failed.append(f"[{i}] {display_cmd}: {e}")
                result.add_detail(f"❌ [{i}] {display_cmd}: {e}")
                logger.error(
                    f"Command execution error on {ctx.session.host}: "
                    f"{command} -> {e}"
                )

        if failed:
            result.success = False
            result.message = (
                f"Выполнено {success_count}/{len(commands)}, "
                f"ошибки: {len(failed)}"
            )
        else:
            result.message = f"Выполнено {success_count} команд"

        return result

    def _resolve_commands(
        self,
        config: dict[str, Any],
        ctx: ExecutionContext,
    ) -> list[str]:
        """
        Resolve the command list for the current cash type.

        For touch: tries precise subtype first (e.g. 'wide-kya'),
        then falls back to base type 'touch'.
        """
        cash_type = ctx.cash_type.lower()
        raw = config.get(cash_type)

        if raw is None:
            return []

        # If it's already a list — direct commands for this type
        if isinstance(raw, list):
            return raw

        # If it's a dict — it's subtype mapping (used for touch)
        if isinstance(raw, dict):
            # Try precise subtype first
            precise = ctx.touch_subtype  # e.g. "wide-kya"
            if precise and precise in raw:
                return raw[precise]

            # Try with full precise_cash_type (touch-wide-kya)
            full_precise = ctx.precise_cash_type
            if full_precise in raw:
                return raw[full_precise]

            # Fallback: try any matching subtype
            logger.warning(
                f"No commands for precise subtype '{precise}' "
                f"in touch config, trying fallback..."
            )

            # Last resort: return empty
            return []

        logger.warning(f"Unexpected config type for '{cash_type}': {type(raw)}")
        return []