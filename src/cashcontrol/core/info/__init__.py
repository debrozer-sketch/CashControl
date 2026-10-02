"""Info subsystem: collectors, snapshot model and problem rules."""

from cashcontrol.core.info.diagnostics import ProblemIssue, check, make_problem_checker
from cashcontrol.core.info.info_manager import (
    ALL_SECTIONS,
    SECTION_GROUPS,
    SECTION_TITLES,
    CashInfoSnapshot,
    CollectionStatus,
    InfoCollector,
    InfoField,
    InfoSection,
    get_info_collector,
)

__all__ = [
    "ALL_SECTIONS",
    "SECTION_GROUPS",
    "SECTION_TITLES",
    "CashInfoSnapshot",
    "CollectionStatus",
    "InfoCollector",
    "InfoField",
    "InfoSection",
    "ProblemIssue",
    "check",
    "get_info_collector",
    "make_problem_checker",
]
