"""
Commands module — executes predefined commands on cash registers.

Supports:
- Simple SSH commands
- Multi-step commands
- Commands with parameters
- Cash-specific commands (restart, reboot)

Usage:
    from cashcontrol.core.commands import CommandExecutor

    executor = CommandExecutor()
    result = await executor.execute_cash_restart(session)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from cashcontrol.infrastructure.audit_logger import audit_log, get_logger

if TYPE_CHECKING:
    from cashcontrol.core.session import CashSession

logger = get_logger()


@dataclass
class CommandExecutionResult:
    """Result of command execution."""

    success: bool
    output: str
    error: str | None = None
    steps_completed: int = 0
    steps_total: int = 1


class CommandExecutor:
    """
    Executes commands on cash registers.

    Provides both generic command execution and specialized methods
    for common cash operations.
    """

    async def execute_simple(
        self, session: CashSession, command: str, timeout: int = 30
    ) -> CommandExecutionResult:
        """
        Execute simple shell command.

        Args:
            session: Connected CashSession
            command: Shell command to execute
            timeout: Command timeout in seconds

        Returns:
            CommandExecutionResult

        Example:
            result = await executor.execute_simple(session, "uptime")
        """
        try:
            logger.info(f"Executing command on {session.host}: {command}")

            ssh_result = await session.ssh.execute(command, timeout=timeout)

            audit_log(
                action_type="command",
                action_name="execute_simple",
                target=session.host,
                result="success" if ssh_result.success else "failure",
                command=command[:100],  # Truncate long commands
            )

            return CommandExecutionResult(
                success=ssh_result.success,
                output=ssh_result.stdout,
                error=ssh_result.stderr if not ssh_result.success else None,
            )

        except Exception as e:
            logger.error(f"Command execution failed on {session.host}: {e}")

            audit_log(
                action_type="command",
                action_name="execute_simple",
                target=session.host,
                result="failure",
                error_message=str(e),
            )

            return CommandExecutionResult(
                success=False, output="", error=str(e)
            )

    async def execute_multi_step(
        self, session: CashSession, commands: list[str], timeout: int = 30
    ) -> CommandExecutionResult:
        """
        Execute multiple commands in sequence.

        Stops on first failure unless command starts with '-' (ignore errors).

        Args:
            session: Connected CashSession
            commands: List of commands
            timeout: Timeout per command

        Returns:
            CommandExecutionResult with aggregated output

        Example:
            commands = [
                "cd /tmp",
                "ls -la",
                "-rm nonexistent"  # Will not stop on error
            ]
            result = await executor.execute_multi_step(session, commands)
        """
        outputs = []
        errors = []
        completed = 0

        try:
            for i, cmd in enumerate(commands):
                # prefix "-" means "run and ignore errors" (don't stop on failure)
                ignore_error = cmd.startswith("-")
                if ignore_error:
                    cmd = cmd[1:].strip()

                logger.debug(f"Step {i+1}/{len(commands)} on {session.host}: {cmd}")

                ssh_result = await session.ssh.execute(cmd, timeout=timeout)

                if ssh_result.stdout:
                    outputs.append(ssh_result.stdout)

                if not ssh_result.success:
                    if ssh_result.stderr:
                        errors.append(f"Step {i+1}: {ssh_result.stderr}")

                    if not ignore_error:
                        # Stop on error
                        logger.error(
                            f"Multi-step command failed at step {i+1} on {session.host}"
                        )
                        break

                completed += 1

            success = completed == len(commands)

            audit_log(
                action_type="command",
                action_name="execute_multi_step",
                target=session.host,
                result="success" if success else "partial",
                steps_completed=completed,
                steps_total=len(commands),
            )

            return CommandExecutionResult(
                success=success,
                output="\n".join(outputs),
                error="\n".join(errors) if errors else None,
                steps_completed=completed,
                steps_total=len(commands),
            )

        except Exception as e:
            logger.error(f"Multi-step execution failed on {session.host}: {e}")

            return CommandExecutionResult(
                success=False,
                output="\n".join(outputs),
                error=str(e),
                steps_completed=completed,
                steps_total=len(commands),
            )

    # ── Cash-specific commands ────────────────────────────────

    async def execute_cash_restart(self, session: CashSession) -> CommandExecutionResult:
        """
        Restart SetRetail cash software (cash restart).
        SSH may drop during restart — this is handled gracefully.
        """
        logger.info(f"Restarting cash software on {session.host}")

        try:
            result = await self.execute_simple(session, "cash restart", timeout=60)
        except Exception:
            # SSH оборвался во время рестарта — это нормально
            result = CommandExecutionResult(
                success=True,
                output="Команда рестарта отправлена.",
                error=None,
            )

        audit_log(
            action_type="cash_operation",
            action_name="cash_restart",
            target=session.host,
            result="success" if result.success else "failure",
        )

        return result

    async def execute_cash_reboot(self, session: CashSession) -> CommandExecutionResult:
        """
        Reboot entire cash register system (cash reboot).

        SSH connection will drop immediately — this is expected behaviour.
        We send the command and don't wait for a response.
        """
        logger.warning(f"Rebooting cash register {session.host}")

        try:
            # Отправляем команду и не ждём ответа — SSH оборвётся, это нормально
            await session.ssh.execute("cash reboot", timeout=5)
        except Exception:
            # ожидаемо: SSH обрывается после отправки ребута
            pass

        audit_log(
            action_type="cash_operation",
            action_name="cash_reboot",
            target=session.host,
            result="success",
        )

        return CommandExecutionResult(
            success=True,
            output="Команда ребута отправлена. Касса перезагружается (~30–60 сек).",
            error=None,
        )