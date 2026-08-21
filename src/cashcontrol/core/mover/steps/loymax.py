"""
loymax.py — Apply Loymax credentials to cash register.

Searches loymax_cashes.csv for the matching login/password based on
shop name and cash number, then writes loymax.properties on the cash.

Config format:
    {
        "csv_file": "loymax_cashes.csv",
        "target_path": "/home/tc/storage/crystal-cash/config/plugins/loymax.properties"
    }

CSV format (columns: login, password):
    login,password
    setkya000301,some_password
    setd001501,another_password
"""

from __future__ import annotations

import csv
from typing import TYPE_CHECKING

from cashcontrol.core.mover.steps.base import BaseStep, ExecutionContext, StepResult
from cashcontrol.infrastructure.audit_logger import get_logger
from cashcontrol.infrastructure.path_resolver import get_mover_data_dir

if TYPE_CHECKING:
    from pathlib import Path

    from cashcontrol.core.mover.scenario import StepDefinition

logger = get_logger()

DEFAULT_TARGET_PATH = (
    "/home/tc/storage/crystal-cash/config/plugins/loymax.properties"
)


def _calculate_match_score(
    csv_login: str,
    shop_type_code: str,
    shop_number: int,
    cash_number: int,
) -> int:
    """
    Calculate how well a CSV login matches the shop and cash.

    Returns score from 0 to 100. Higher is better.
    Logic ported from bot's mover_loymax.py.
    """
    score = 0

    # 1. Check prefix
    expected_prefix = f"set{shop_type_code}"
    if not csv_login.lower().startswith(expected_prefix.lower()):
        return 0
    score += 20

    # 2. Extract digits
    digits = "".join(char for char in csv_login if char.isdigit())
    if not digits:
        return 0

    # 3. Shop number match (first 4 digits)
    if len(digits) >= 4:
        csv_shop_part = digits[:4]
        try:
            csv_shop_num = int(csv_shop_part)
            if str(csv_shop_num).zfill(4) == str(shop_number).zfill(4):
                score += 40
            elif abs(csv_shop_num - shop_number) <= 10:
                score += 20
            elif abs(csv_shop_num - shop_number) <= 100:
                score += 10
        except ValueError:
            pass

    # 4. Cash number match
    cash_number_str = str(cash_number)
    cash_found = False
    if len(digits) > 4:
        remaining = digits[4:]
        if remaining == cash_number_str.zfill(2) or remaining == cash_number_str.zfill(3):
            score += 30
            cash_found = True
        elif cash_number_str in remaining:
            score += 15
            cash_found = True

    if not cash_found and cash_number_str in csv_login:
        score += 10

    return min(score, 100)


def _parse_shop_info(shop_name: str) -> tuple[str, int] | None:
    """
    Parse shop name into (type_code, number).

    'КЯ-3'  → ('kya', 3)
    'Д-15'  → ('d', 15)
    Returns None if format unrecognised.
    """
    name_lower = shop_name.strip().lower()

    if name_lower.startswith("кя-"):
        try:
            return ("kya", int(shop_name[3:].strip()))
        except ValueError:
            return None
    elif name_lower.startswith("д-"):
        try:
            return ("d", int(shop_name[2:].strip()))
        except ValueError:
            return None
    return None


class LoymaxStep(BaseStep):
    """Find Loymax credentials in CSV and write to cash register."""

    async def execute(
        self,
        step_def: StepDefinition,
        ctx: ExecutionContext,
    ) -> StepResult:
        config = step_def.config
        csv_filename = config.get("csv_file", "loymax_cashes.csv")
        target_path = config.get("target_path", DEFAULT_TARGET_PATH)

        # Locate CSV
        csv_path = get_mover_data_dir() / csv_filename
        if not csv_path.exists():
            return StepResult(
                success=False,
                message=f"CSV-файл не найден: {csv_filename}",
            )

        # Parse shop info
        parsed = _parse_shop_info(ctx.shop_name)
        if not parsed:
            return StepResult(
                success=False,
                message=f"Некорректный формат магазина: '{ctx.shop_name}'",
            )
        shop_type_code, shop_number = parsed

        try:
            cash_number = int(ctx.cash_number)
        except (ValueError, TypeError):
            return StepResult(
                success=False,
                message=f"Некорректный номер кассы: '{ctx.cash_number}'",
            )

        await ctx.log(
            f"Поиск Loymax для {ctx.shop_name} касса {cash_number}..."
        )

        # Search CSV
        best_match: tuple[str, str] | None = None
        best_score = -1

        try:
            rows = self._read_csv(csv_path)
        except Exception as e:
            return StepResult(success=False, message=f"Ошибка чтения CSV: {e}")

        for login, password in rows:
            if login.upper() == "FR_DEBET":
                continue
            score = _calculate_match_score(
                login, shop_type_code, shop_number, cash_number
            )
            if score > best_score:
                best_score = score
                best_match = (login, password)

        # Fallback search if no good match
        if not best_match or best_score < 20:
            best_match = self._fallback_search(
                rows, shop_type_code, shop_number
            )

        if not best_match:
            return StepResult(
                success=False,
                message=(
                    f"Loymax не найден для {ctx.shop_name} "
                    f"касса {cash_number}"
                ),
            )

        new_login, new_password = best_match
        await ctx.log(f"Найден: {new_login}")

        # Write to cash via printf (compatible with Dropbear/Tiny Core)
        safe_login = self._escape_for_printf(new_login)
        safe_password = self._escape_for_printf(new_password)

        write_cmd = (
            f"printf 'loymax.login={safe_login}\\n"
            f"loymax.password={safe_password}\\n' "
            f"> '{target_path}'"
        )

        try:
            cmd_result = await ctx.session.ssh.execute(write_cmd)
            if not cmd_result.success:
                return StepResult(
                    success=False,
                    message=f"Ошибка записи: {cmd_result.stderr[:200]}",
                )
        except Exception as e:
            return StepResult(success=False, message=f"Ошибка SSH: {e}")

        return StepResult(
            success=True,
            message=f"loymax.login={new_login}",
            data={"login": new_login},
        )

    def _read_csv(self, path: Path) -> list[tuple[str, str]]:
        """Read CSV and return list of (login, password) tuples."""
        rows: list[tuple[str, str]] = []

        # Try UTF-8 first, fallback to cp1251
        # Delimiter: auto-detect (try ';' first since our CSVs use it)
        for encoding in ("utf-8", "cp1251"):
            try:
                with open(path, encoding=encoding) as f:
                    # Peek at first line to detect delimiter
                    first_line = f.readline()
                    f.seek(0)
                    delimiter = ";" if ";" in first_line else ","

                    reader = csv.DictReader(f, delimiter=delimiter)
                    for row in reader:
                        # Normalize keys (remove BOM, strip)
                        norm = {
                            k.strip().lstrip("\ufeff"): v
                            for k, v in row.items()
                        }
                        login = norm.get("login", "").strip()
                        password = norm.get("password", "").strip()
                        # Strip surrounding quotes from password
                        if password.startswith('"') and password.endswith('"'):
                            password = password[1:-1]
                        if login:
                            rows.append((login, password))
                return rows
            except UnicodeDecodeError:
                continue

        return rows

    def _fallback_search(
        self,
        rows: list[tuple[str, str]],
        shop_type_code: str,
        shop_number: int,
    ) -> tuple[str, str] | None:
        """Fallback search by shop number substring."""
        prefix = f"set{shop_type_code}"
        shop_str = str(shop_number)

        # Try exact shop number match
        for login, pwd in rows:
            if login.upper() == "FR_DEBET":
                continue
            if shop_str in login and login.lower().startswith(prefix.lower()):
                return (login, pwd)

        # Try just prefix match
        for login, pwd in rows:
            if login.upper() == "FR_DEBET":
                continue
            if login.lower().startswith(prefix.lower()):
                return (login, pwd)

        return None

    @staticmethod
    def _escape_for_printf(s: str) -> str:
        """Escape string for shell printf and single-quoted context."""
        s = s.replace("'", "'\"'\"'")
        s = s.replace("%", "%%").replace("\\", "\\\\")
        return s