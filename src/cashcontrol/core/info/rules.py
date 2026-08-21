"""
Problem rules — checks collected info for known issues.

Each rule inspects the CashInfoSnapshot and returns a ProblemIssue
if something is wrong. Rules are registered in PROBLEM_RULES list.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

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


class ProblemChecker:
    """Runs all registered rules against a snapshot and collects issues."""

    def __init__(self) -> None:
        self._rules: list[dict[str, Any]] = PROBLEM_RULES

    def check(
        self, snapshot: CashInfoSnapshot, cash_type: str
    ) -> list[ProblemIssue]:
        issues: list[ProblemIssue] = []
        for rule in self._rules:
            if "cash_types" in rule:
                if cash_type not in rule["cash_types"]:
                    continue
            try:
                issue = rule["check"](snapshot, cash_type)
                if issue is not None:
                    issues.append(issue)
            except Exception:
                # ожидаемо: сбой одного правила не валит весь анализ
                pass
        return issues


# ── Rule definitions ─────────────────────────────────────────────────────────
# Each rule is a dict with:
#   "check": callable(snapshot, cash_type) -> ProblemIssue | None
#   "cash_types": optional list of applicable cash types

PROBLEM_RULES: list[dict[str, Any]] = [
    {
        # Банк: EnableUSB=1 — проверка, что USB-режим включён
        "check": lambda snap, _: (
            ProblemIssue("Банк", "EnableUSB=1")
            if snap.bank_terminal.data.get("bank_usb_mode") == "1"
            else None
        ),
    },
    {
        # SCO3: проверка paymentTypeRanks в БД
        "cash_types": ["sco3"],
        "check": lambda snap, _: _check_payment_ranks(snap),
    },
    {
        # POS/Touch: проверка retailOnlyDrawerClose
        "cash_types": ["pos", "touch"],
        "check": lambda snap, _: _check_drawer_close(snap),
    },
]


def _check_payment_ranks(snap: CashInfoSnapshot) -> ProblemIssue | None:
    raw = snap.payment_ranks.data.get("payment_ranks_raw")
    if raw is None:
        return ProblemIssue("Типы оплат", "не удалось получить данные из БД", "error")
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        return ProblemIssue("Типы оплат", "некорректный JSON в БД", "error")

    if parsed != _REFERENCE_PAYMENT_RANKS:
        return ProblemIssue("Типы оплат", "некорректные типы оплат", "warning")

    return None


def _check_drawer_close(snap: CashInfoSnapshot) -> ProblemIssue | None:
    raw = snap.drawer_close.data.get("drawer_close_raw")
    if raw is None:
        return ProblemIssue("Денежный ящик", "не удалось получить данные из БД", "error")
    val = raw.strip().lower() if isinstance(raw, str) else str(raw).lower()
    if val == "true" or val == "t":
        return ProblemIssue(
            "Денежный ящик", "возможна ошибка Закройте денежный ящик", "warning"
        )
    return None