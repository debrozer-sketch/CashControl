"""
Unified command loader — loads commands from TOML and Python files.

TOML format (simple shell commands):
    [command]
    name        = "restart_cash"
    description = "Restart cash software"
    category    = "builtin"
    cash_types  = ["pos", "touch"]
    timeout     = 20

    [[steps]]
    label   = "Restart service"
    command = "sudo systemctl restart cash"

Python format (commands with logic):
    # [command]
    # name        = find_cashier
    # description = Search cashier login in config
    # category    = info
    # timeout     = 15

    async def execute(session, **kwargs) -> str:
        ...
"""

from __future__ import annotations

import importlib.util
import sys as _sys
from typing import TYPE_CHECKING, Any

from cashcontrol.actions_registry import Action
from cashcontrol.infrastructure.audit_logger import get_logger

if TYPE_CHECKING:
    from pathlib import Path

logger = get_logger()


class CommandLoader:
    """Unified command loader for TOML and Python command files."""

    def __init__(self, commands_dir: Path) -> None:
        self._dir = commands_dir
        self._errors: list[str] = []

    def load_all(self) -> list[Action]:
        """Load all valid commands from the commands directory."""
        self._errors.clear()
        actions: list[Action] = []

        if not self._dir.exists():
            logger.warning(f"Commands directory not found: {self._dir}")
            return actions

        for path in sorted(self._dir.iterdir()):
            if path.suffix == ".toml":
                action = self._load_toml(path)
            elif path.suffix == ".py":
                action = self._load_python(path)
            else:
                continue
            if action is not None:
                actions.append(action)

        logger.info(f"Loaded {len(actions)} commands from {self._dir}")
        return actions

    def _load_toml(self, path: Path) -> Action | None:
        """Load a TOML command file."""
        try:
            import tomllib
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            meta = data["command"]
            steps = data.get("steps", [])

            name = meta["name"]
            timeout = meta.get("timeout", 30)

            async def handler(session, _steps=steps, _name=name, _timeout=timeout, **kwargs):
                outputs = []
                for step in _steps:
                    cmd = step.get("command", "")
                    # Шаг может объявить, что обрыв соединения после отправки
                    # команды — ожидаемое поведение (reboot и т.п.)
                    ignore_dc = (step.get("ignore_disconnect", False)
                                 or meta.get("ignore_disconnect", False))
                    try:
                        result = await session.ssh.execute(cmd, timeout=_timeout)
                        outputs.append(f"$ {cmd}")
                        if result.stdout:
                            outputs.append(result.stdout.strip())
                        if result.stderr:
                            outputs.append(result.stderr.strip())
                    except Exception as e:
                        if ignore_dc:
                            outputs.append(f"$ {cmd}")
                            outputs.append(
                                "Соединение закрыто кассой — команда отправлена")
                            continue
                        return {
                            "success": False,
                            "message": f"Command '{_name}' failed at step '{step.get('label', '')}': {e}",
                            "details": {"output": "\n".join(outputs), "errors": str(e)},
                        }
                return {
                    "success": True,
                    "message": f"Command '{_name}' executed",
                    "details": {"output": "\n".join(outputs), "errors": ""},
                }

            return Action(
                name=name,
                description=meta.get("description", name),
                category=meta.get("category", "other"),
                cash_types=meta.get("cash_types"),
                requires_confirmation=meta.get("requires_confirmation", False),
                show_output=meta.get("show_output", True),
                timeout=timeout,
                handler=handler,
                source=str(path),
                is_builtin=meta.get("category") == "builtin",
            )
        except Exception:
            logger.exception(f"Failed to load TOML command from {path}")
            self._errors.append(str(path))
            return None

    def _load_python(self, path: Path) -> Action | None:
        """Load a Python command file with # [command] metadata block."""
        try:
            source = path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"Cannot read {path}: {e}")
            return None

        meta = self._parse_py_metadata(source)
        if not meta:
            logger.warning(f"Skipping {path.name}: no # [command] metadata block")
            return None

        name = meta.get("name", path.stem)

        if "async def execute(session" not in source:
            logger.warning(f"Skipping {path.name}: missing 'async def execute(session, **kwargs)'")
            return None

        module_name = f"cashcontrol.commands.{path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            logger.error(f"Cannot create spec for {path}")
            return None

        module = importlib.util.module_from_spec(spec)
        _sys.modules[module_name] = module
        spec.loader.exec_module(module)

        execute_fn = getattr(module, "execute", None)
        if not callable(execute_fn):
            logger.warning(f"No callable 'execute' in {path.name}")
            return None

        timeout = int(meta.get("timeout", 30))

        input_prompt = getattr(module, "INPUT_PROMPT", None)

        async def handler(session, fn=execute_fn, _name=name, _timeout=timeout, **kwargs):
            try:
                import asyncio
                result = await asyncio.wait_for(fn(session, **kwargs), timeout=_timeout)
                return {
                    "success": True,
                    "message": f"Command '{_name}' executed",
                    "details": {"output": str(result) if result is not None else "", "errors": ""},
                }
            except Exception as e:
                return {
                    "success": False,
                    "message": f"Command '{_name}' failed: {e}",
                    "details": {"output": "", "errors": str(e)},
                }

        return Action(
            name=name,
            description=meta.get("description", name),
            category=meta.get("category", "other"),
            cash_types=meta.get("cash_types"),
            requires_confirmation=meta.get("requires_confirmation", "false").lower() == "true",
            show_output=meta.get("show_output", "true").lower() == "true",
            timeout=timeout,
            handler=handler,
            source=str(path),
            is_builtin=meta.get("category") == "builtin",
            input_prompt=input_prompt,
        )

    @staticmethod
    def _quote_toml_value(val: str) -> str:
        """Auto-quote a TOML value if it is not a bare literal (int, float, bool, array)."""
        v = val.strip()
        if not v:
            return '""'
        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
            return v
        if v.lower() in ("true", "false"):
            return v
        if v.lstrip("-+").isdigit():
            return v
        try:
            float(v)
            return v
        except ValueError:
            pass
        if v.startswith("[") and v.endswith("]"):
            return v
        return f'"{v}"'

    def _parse_py_metadata(self, source: str) -> dict[str, Any]:
        """
        Parse # [command] block from the start of a Python file.

        Strips '# ' prefix from each line and parses as TOML.
        Returns the [command] section as a dict, or empty dict if not found.
        """
        lines: list[str] = []
        in_block = False
        for line in source.splitlines():
            stripped = line.strip()
            if stripped == "# [command]":
                in_block = True
                lines.append("[command]")
                continue
            if in_block:
                if stripped.startswith("#"):
                    content = stripped[1:].lstrip()
                    if "=" in content:
                        key, _, val = content.partition("=")
                        content = f"{key.strip()} = {self._quote_toml_value(val)}"
                    lines.append(content)
                else:
                    break
        if not lines:
            return {}
        import tomllib
        try:
            return tomllib.loads("\n".join(lines)).get("command", {})
        except Exception:
            logger.warning("Failed to parse # [command] metadata as TOML")
            return {}

    @property
    def errors(self) -> list[str]:
        return list(self._errors)