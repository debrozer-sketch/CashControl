"""
Diagnostics — declarative checks over collected info (Phase 2.5 ABC).

Each check is a DiagnosticCheck subclass inspecting the CashInfoSnapshot
and returning a ProblemIssue when something is wrong. Checks are
registered in DIAGNOSTIC_CHECKS.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from cashcontrol.core.cash_types import has_feature

if TYPE_CHECKING:
    from cashcontrol.core.info.info_manager import CashInfoSnapshot


@dataclass
class ProblemIssue:
    section: str
    message: str
    severity: str = "warning"  # "warning" | "error"


_REFERENCE_PAYMENT_RANKS = {
    "paymentTypesRanks": [
        {"paymentId": "BankCardPaymentEntity", "bankId": "Сбербанк", "fastAccessRank": 1, "rank": 1},
        {"paymentId": "BankQRPaymentEntity", "bankId": "ГазпромБанк СБП", "fastAccessRank": 2, "rank": 2},
    ],
    "paymentTypesWithCounterpartyRanks": [
        {"paymentId": "BankCardPaymentEntity", "bankId": "Сбербанк", "fastAccessRank": 1, "rank": 1},
        {"paymentId": "BankQRPaymentEntity", "bankId": "ГазпромБанк СБП", "fastAccessRank": 2, "rank": 2},
    ],
}


class DiagnosticCheck(ABC):
    """Base class for one diagnostic rule."""

    id: str = "check"

    def applies_to(self, cash_type: str) -> bool:
        """Override to restrict the check to specific cash types/features."""
        return True

    @abstractmethod
    def check(self, snapshot: CashInfoSnapshot, cash_type: str) -> ProblemIssue | None:
        ...


class BankUsbModeCheck(DiagnosticCheck):
    """Банк: EnableUSB=1 — проверка, что USB-режим включён."""

    id = "bank_usb_mode"

    def check(self, snapshot: CashInfoSnapshot, cash_type: str) -> ProblemIssue | None:
        if snapshot.bank_terminal.data.get("bank_usb_mode") == "1":
            return ProblemIssue("Банк", "EnableUSB=1")
        return None


class PaymentRanksCheck(DiagnosticCheck):
    """SCO3: проверка paymentTypeRanks в БД."""

    id = "payment_ranks"

    def applies_to(self, cash_type: str) -> bool:
        return has_feature(cash_type, "payment_ranks")

    def check(self, snapshot: CashInfoSnapshot, cash_type: str) -> ProblemIssue | None:
        raw = snapshot.payment_ranks.data.get("payment_ranks_raw")
        if raw is None:
            return ProblemIssue(
                "Типы оплат", "не удалось получить данные из БД", "error"
            )
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError:
            return ProblemIssue("Типы оплат", "некорректный JSON в БД", "error")

        if parsed != _REFERENCE_PAYMENT_RANKS:
            return ProblemIssue("Типы оплат", "некорректные типы оплат", "warning")
        return None


class DrawerCloseCheck(DiagnosticCheck):
    """POS/Touch: проверка retailOnlyDrawerClose."""

    id = "drawer_close"

    def applies_to(self, cash_type: str) -> bool:
        return has_feature(cash_type, "drawer_close")

    def check(self, snapshot: CashInfoSnapshot, cash_type: str) -> ProblemIssue | None:
        raw = snapshot.drawer_close.data.get("drawer_close_raw")
        if raw is None:
            return ProblemIssue(
                "Денежный ящик", "не удалось получить данные из БД", "error"
            )
        val = raw.strip().lower() if isinstance(raw, str) else str(raw).lower()
        if val in ("true", "t"):
            return ProblemIssue(
                "Денежный ящик", "возможна ошибка Закройте денежный ящик", "warning"
            )
        return None


DIAGNOSTIC_CHECKS: list[DiagnosticCheck] = [
    BankUsbModeCheck(),
    PaymentRanksCheck(),
    DrawerCloseCheck(),
]


class ProblemChecker:
    """Runs all registered checks against a snapshot and collects issues."""

    def __init__(self) -> None:
        self._checks: list[DiagnosticCheck] = DIAGNOSTIC_CHECKS

    def check(
        self, snapshot: CashInfoSnapshot, cash_type: str
    ) -> list[ProblemIssue]:
        issues: list[ProblemIssue] = []
        for check in self._checks:
            try:
                if not check.applies_to(cash_type):
                    continue
                issue = check.check(snapshot, cash_type)
                if issue is not None:
                    issues.append(issue)
            except Exception:
                # ожидаемо: сбой одной проверки не валит весь анализ
                pass
        return issues
