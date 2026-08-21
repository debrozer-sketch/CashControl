"""
qrid.py — Apply QRID (Gazprom SBP) to bank config on POS cash register.

Searches qrid.csv for the matching QRID based on shop name and cash number,
then updates bank-gazprom_sbp-config.xml on the cash via sed.

Config format:
    {
        "csv_file": "qrid.csv",
        "target_path": "/home/tc/storage/crystal-cash/config/plugins/bank-gazprom_sbp-config.xml"
    }

CSV format (semicolon-separated, columns: TT, KASS, QRID):
    TT;KASS;QRID
    КЯ3;1;ABC123DEF456
    Д15;22;XYZ789GHI012
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
    "/home/tc/storage/crystal-cash/config/plugins/"
    "bank-gazprom_sbp-config.xml"
)


class QridStep(BaseStep):
    """Find QRID in CSV and apply to bank config XML on cash register."""

    async def execute(
        self,
        step_def: StepDefinition,
        ctx: ExecutionContext,
    ) -> StepResult:
        config = step_def.config
        csv_filename = config.get("csv_file", "qrid.csv")
        target_path = config.get("target_path", DEFAULT_TARGET_PATH)

        # Locate CSV
        csv_path = get_mover_data_dir() / csv_filename
        if not csv_path.exists():
            return StepResult(
                success=False,
                message=f"CSV-файл не найден: {csv_filename}",
            )

        # Validate shop name format
        shop_name = ctx.shop_name.strip()
        if not shop_name.lower().startswith(("д-", "кя-")):
            return StepResult(
                success=False,
                message=f"Некорректный формат магазина: '{shop_name}'",
            )

        cash_number_raw = ctx.cash_number.strip()
        if not cash_number_raw:
            return StepResult(
                success=False,
                message="Номер кассы не указан",
            )

        await ctx.log(
            f"Поиск QRID для {shop_name} касса {cash_number_raw}..."
        )

        # Search CSV
        qrid_value = self._find_qrid(csv_path, shop_name, cash_number_raw)

        if not qrid_value:
            return StepResult(
                success=False,
                message=(
                    f"QRID не найден для {shop_name} "
                    f"касса {cash_number_raw}"
                ),
            )

        await ctx.log(f"Найден QRID: {qrid_value}")

        # Apply via sed on the cash register
        escaped_qrid = (
            qrid_value
            .replace("&", r"\&")
            .replace("\\", r"\\")
            .replace('"', r'\"')
            .replace("'", r"'\''")
        )

        sed_cmd = (
            f"sed -i '/key=\"cashLinkQrId\"/ "
            f"s/value=\"[^\"]*\"/value=\"{escaped_qrid}\"/' "
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
            message=f"QRID: {qrid_value}",
            data={"qrid": qrid_value},
        )

    def _find_qrid(
        self,
        csv_path: Path,
        shop_name: str,
        cash_number: str,
    ) -> str | None:
        """Search CSV for matching QRID."""
        shop_normalized = self._normalize_shop(shop_name)

        for encoding in ("utf-8", "cp1251"):
            try:
                with open(csv_path, encoding=encoding) as f:
                    reader = csv.DictReader(f, delimiter=";")
                    for row in reader:
                        # Normalize keys (strip BOM)
                        norm = {
                            k.strip().lstrip("\ufeff"): v
                            for k, v in row.items()
                        }
                        csv_shop = self._normalize_shop(
                            norm.get("TT", "").strip()
                        )
                        csv_cash = norm.get("KASS", "").strip()

                        if csv_shop == shop_normalized and csv_cash == cash_number:
                            return norm.get("QRID", "").strip() or None

                return None  # Parsed OK but no match
            except UnicodeDecodeError:
                continue

        return None

    @staticmethod
    def _normalize_shop(name: str) -> str:
        """
        Normalize shop name for comparison.

        Handles formats: 'КЯ-44', 'КЯ44', 'Д-1', 'Д01', 'Д001'
        Result: prefix + number without leading zeros, e.g. 'кя44', 'д1'
        """
        import re
        s = name.lower().replace("-", "").replace(" ", "")
        # Split into alpha prefix and numeric suffix
        m = re.match(r"^([а-яa-z]+)(\d+)$", s)
        if m:
            prefix = m.group(1)
            number = str(int(m.group(2)))  # strip leading zeros
            return prefix + number
        return s