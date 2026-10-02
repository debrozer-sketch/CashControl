"""
Actions registry — central registry for all available actions.

Actions can be:
- Built-in (from actions/default_actions.py)
- User-defined (from modules/actions/*.py)
- Loaded dynamically at runtime

Usage:
from cashcontrol.actions_registry import ActionsRegistry

    registry = ActionsRegistry()
    await registry.execute_action("restart_cash", session)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from cashcontrol.infrastructure.audit_logger import audit_log, get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from cashcontrol.core.session import CashSession

logger = get_logger()


@dataclass
class Action:
    """Represents a single action."""

    name: str
    description: str
    category: str
    handler: Callable
    requires_confirmation: bool = False
    show_output: bool = True  # show result dialog after execution
    input_prompt: str | None = None  # если задан — показать диалог ввода перед выполнением
    timeout: int = 30
    cash_types: list[str] | None = None  # list of register types, None = all
    source: str | None = None  # path to source file
    is_builtin: bool = False  # builtin commands survive reload


@dataclass
class ActionResult:
    """Result of action execution."""

    success: bool
    message: str
    details: dict[str, Any] | None = None
    error: str | None = None


class ActionsRegistry:
    """
    Central registry for all actions.

    Manages built-in and user-defined actions, provides
    unified execution interface.
    """

    def __init__(self) -> None:
        self._actions: dict[str, Action] = {}
        self._loaded = False

    def ensure_loaded(self) -> None:
        """Ensure commands are loaded. No-op for now (loading in __init__).
        Will be used when loading becomes lazy (Step 5)."""
        if not self._loaded:
            self._load_all()
            self._loaded = True

    def _load_all(self) -> None:
        """Load all commands from commands/ directory via CommandLoader."""
        from cashcontrol.infrastructure.command_loader import CommandLoader
        from cashcontrol.infrastructure.path_resolver import get_commands_dir

        loader = CommandLoader(get_commands_dir())
        actions = loader.load_all()
        for action in actions:
            self._actions[action.name] = action
        logger.info(f"Loaded {len(actions)} commands from {get_commands_dir()}")

    def reload_commands(self) -> None:
        """Reload only non-builtin commands (builtin ones survive)."""
        builtin = {k: v for k, v in self._actions.items() if v.is_builtin}
        self._actions = builtin

        from cashcontrol.infrastructure.command_loader import CommandLoader
        from cashcontrol.infrastructure.path_resolver import get_commands_dir

        loader = CommandLoader(get_commands_dir())
        for action in loader.load_all():
            if not action.is_builtin:
                self._actions[action.name] = action
        logger.info(f"Reloaded commands: {len(self._actions)} total")

    async def execute_action(
        self, action_name: str, session: CashSession, **kwargs: Any
    ) -> ActionResult:
        """
        Execute action by name.

        Args:
            action_name: Name of action to execute
            session: Connected CashSession
            **kwargs: Additional parameters for action

        Returns:
            ActionResult

        Example:
            result = await registry.execute_action("restart_cash", session)
            if result.success:
                print(result.message)
        """
        action = self._actions.get(action_name)

        if not action:
            logger.error(f"Action not found: {action_name}")
            return ActionResult(
                success=False,
                message=f"Action '{action_name}' not found",
                error="Action not registered",
            )

        try:
            logger.info(f"Executing action '{action_name}' on {session.host}")

            # Execute action handler
            result = await action.handler(session, **kwargs)

            # Convert to ActionResult if handler returned dict
            if isinstance(result, dict):
                result = ActionResult(
                    success=result.get("success", True),
                    message=result.get("message", ""),
                    details=result.get("details"),
                    error=result.get("error"),
                )

            audit_log(
                action_type="action",
                action_name=action_name,
                target=session.host,
                result="success" if result.success else "failure",
                description=action.description or action_name,
            )

            return result

        except Exception as e:
            logger.exception(f"Action '{action_name}' failed on {session.host}")

            audit_log(
                action_type="action",
                action_name=action_name,
                target=session.host,
                result="failure",
                description=action.description if action else action_name,
                error_message=str(e),
            )

            return ActionResult(
                success=False,
                message=f"Action failed: {e}",
                error=str(e),
            )

    def get_action(self, action_name: str) -> Action | None:
        """Get action by name."""
        return self._actions.get(action_name)

    def get_all_actions(self) -> list[Action]:
        """Get list of all registered actions."""
        return list(self._actions.values())

    def get_actions_by_category(self, category: str) -> list[Action]:
        """Get actions filtered by category."""
        return [a for a in self._actions.values() if a.category == category]

    def __repr__(self) -> str:
        builtin = len([a for a in self._actions.values() if a.category == "builtin"])
        user = len([a for a in self._actions.values() if a.category in ("user", "json")])
        return f"<ActionsRegistry builtin={builtin} user={user}>"
