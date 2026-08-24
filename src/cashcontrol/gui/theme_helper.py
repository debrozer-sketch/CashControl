"""Centralized theme helpers for CashControl GUI.

Provides dynamic color resolution based on current qfluentwidgets theme.
All GUI modules should use these helpers instead of hardcoding hex colors.
"""

from __future__ import annotations

import re


def is_dark() -> bool:
    """Return True if current qfluentwidgets theme is dark."""
    try:
        from qfluentwidgets import isDarkTheme
        return isDarkTheme()
    except Exception:
        return False


# ── Color palette ──────────────────────────────────────────────────────

# Semantic color pairs: (light_value, dark_value)
# ── Vantage «Пульт диспетчера касс» (dash-ключи для QSS) ──
TOKENS = {
    "bg-base":    ("#F3F1EC", "#15181D"),
    "bg-elev":    ("#FBFAF7", "#1E2229"),
    "bg-sunken":  ("#ECE9E1", "#111419"),
    "bg-hover":   ("#EBE8DF", "#272C35"),
    "bg-pressed": ("#E1DDD2", "#2E3440"),
    "bg-chip":    ("#ECEAE2", "#262B33"),
    "vnc-bg":     ("#12151A", "#0E1116"),
    "text-primary":   ("#20242B", "#E4E7EB"),
    "text-secondary": ("#5C6270", "#A6AEB9"),
    "text-disabled":  ("#9BA1A9", "#6B7280"),
    "text-data":      ("#1F3A52", "#C7D5E4"),
    "line-weak":   ("#E3DFD5", "#272C34"),
    "line-strong": ("#D2CDC0", "#353C47"),
    "accent":         ("#0F766E", "#55C0B4"),
    "accent-hover":   ("#0C6560", "#6BCCC1"),
    "accent-pressed": ("#0A5751", "#3FA79B"),
    "soft-accent":    ("#DDEDE9", "#17322F"),
    "ok":   ("#2E7D32", "#66BB6A"),
    "warn": ("#A16207", "#E3B341"),
    "err":  ("#B3261E", "#E57373"),
    "info": ("#33608C", "#86AEDD"),
    "soft-ok":   ("#E2EFE1", "#1C3024"),
    "soft-warn": ("#F6ECD7", "#372F18"),
    "soft-err":  ("#F5E2E0", "#3A2223"),
    "sel-bg":   ("#CFE4E0", "#23423D"),
    "sel-text": ("#20242B", "#E4E7EB"),
    "scroll-handle": ("#C6C1B4", "#3A414C"),
    "tooltip-bg":   ("#272C33", "#272C33"),
    "tooltip-text": ("#F2F4F6", "#F2F4F6"),
    "ping-ok":      ("#2B8A3E", "#52BD68"),
    "ping-slow":    ("#B58900", "#E0B13C"),
    "ping-timeout": ("#C0352B", "#DE5D52"),
    "ping-unknown": ("#9AA1A9", "#767E89"),
}

# Алиасы legacy underscore-ключей → TOKENS
_COLORS = {
    "bg_primary": TOKENS["bg-base"],
    "bg_secondary": TOKENS["bg-base"],
    "bg_card": TOKENS["bg-elev"],
    "bg_surface": TOKENS["bg-elev"],
    "bg_elevated": TOKENS["bg-elev"],
    "bg_input": TOKENS["bg-elev"],
    "bg_tertiary": TOKENS["bg-sunken"],
    "bg_tooltip": TOKENS["tooltip-bg"],
    "bg_dialog": TOKENS["bg-base"],
    "bg_hover": TOKENS["bg-hover"],
    "bg_pressed": TOKENS["bg-pressed"],
    "bg_selected": TOKENS["sel-bg"],
    "bg_warning": TOKENS["soft-warn"],
    "bg_info": TOKENS["soft-accent"],
    "bg_success": TOKENS["soft-ok"],
    "bg_danger": TOKENS["soft-err"],
    "bg_table_alt": TOKENS["bg-elev"],
    "bg_code": TOKENS["bg-sunken"],
    "text_primary": TOKENS["text-primary"],
    "text_secondary": TOKENS["text-secondary"],
    "text_tertiary": TOKENS["text-secondary"],
    "text_disabled": TOKENS["text-disabled"],
    "text_on_accent": ("#FFFFFF", "#0A2723"),
    "text_link": TOKENS["info"],
    "text_heading": TOKENS["text-primary"],
    "text_code": TOKENS["text-data"],
    "border_primary": TOKENS["line-strong"],
    "border_subtle": TOKENS["line-weak"],
    "border_secondary": TOKENS["line-weak"],
    "border_input": TOKENS["line-strong"],
    "border_focus": TOKENS["accent"],
    "border_light": TOKENS["line-weak"],
    "tab_hover_border": TOKENS["line-strong"],
    "control_border_bottom": TOKENS["line-strong"],
    "accent_text": TOKENS["accent"],
    "accent_fill": TOKENS["accent"],
    "accent_fill_hover": TOKENS["accent-hover"],
    "accent_fill_pressed": TOKENS["accent-pressed"],
    "accent_subtle": TOKENS["soft-accent"],
    "accent_subtle_hover": TOKENS["bg-hover"],
    "accent_light": TOKENS["soft-accent"],
    "accent_hover": TOKENS["accent-hover"],
    "accent_pressed": TOKENS["accent-pressed"],
    "success": TOKENS["ok"],
    "warning": TOKENS["warn"],
    "error": TOKENS["err"],
    "info": TOKENS["info"],
    "status_ok": TOKENS["ping-ok"],
    "status_warn": TOKENS["ping-slow"],
    "status_error": TOKENS["ping-timeout"],
    "status_neutral": TOKENS["ping-unknown"],
    "ok_subtle": TOKENS["soft-ok"],
    "warn_subtle": TOKENS["soft-warn"],
    "error_subtle": TOKENS["soft-err"],
    "bg_ok": TOKENS["soft-ok"],
    "bg_slow": TOKENS["soft-warn"],
    "bg_timeout": TOKENS["soft-err"],
    "control_fill": TOKENS["bg-elev"],
    "control_fill_hover": TOKENS["bg-hover"],
    "control_fill_pressed": TOKENS["bg-pressed"],
    "control_fill_disabled": TOKENS["bg-sunken"],
    "scrollbar_thumb": TOKENS["scroll-handle"],
    "scrollbar_thumb_hover": TOKENS["line-strong"],
    "scrollbar_hover": TOKENS["line-strong"],
    "sql_bg": TOKENS["bg-sunken"],
    "sql_text": TOKENS["text-primary"],
    "sql_keyword": TOKENS["accent"],
    "sql_string": TOKENS["text-data"],
    "sql_number": TOKENS["info"],
    "sql_comment": TOKENS["text-disabled"],
    "sql_function": TOKENS["text-secondary"],
    "separator": TOKENS["line-weak"],
    "btn_danger_bg": TOKENS["soft-err"],
    "btn_danger_hover": TOKENS["err"],
    "btn_flat_hover": TOKENS["bg-hover"],
    "btn_cancel_bg": TOKENS["bg-pressed"],
    "vnc_bg": TOKENS["vnc-bg"],
    "table_header_bg": TOKENS["bg-base"],
    "table_header_text": TOKENS["text-secondary"],
    "warning_border": TOKENS["warn"],
    "warning_text": TOKENS["warn"],
    "warning_bg": TOKENS["soft-warn"],
}


def color(name: str) -> str:
    """Return hex color for the given semantic name based on current theme.

    Usage:
        from cashcontrol.gui.theme_helper import color
        widget.setStyleSheet(f"color: {color('text_primary')};")
    """
    pair = _COLORS.get(name)
    if pair is None:
        return "#ff00ff"  # magenta — easy to spot missing colors
    return pair[1] if is_dark() else pair[0]


def resolve(qss: str) -> str:
    """Подстановка @dash-токенов vantage в QSS."""
    def repl(m: re.Match[str]) -> str:
        name = m.group(1)
        if name in TOKENS:
            return color(name)
        return m.group(0)

    return re.sub(r"@([a-z0-9-]+)", repl, qss)


def colors(*names: str) -> tuple[str, ...]:
    """Return multiple colors at once.

    Usage:
        fg, bg, border = colors('text_primary', 'bg_surface', 'border_primary')
    """
    return tuple(color(n) for n in names)


def styled(template: str, **kwargs: str) -> str:
    """Build a stylesheet string substituting color names.

    Usage:
        widget.setStyleSheet(styled(
            "color: {fg}; background: {bg};",
            fg="text_primary",
            bg="bg_surface",
        ))
    """
    resolved = {k: color(v) for k, v in kwargs.items()}
    return template.format(**resolved)


# ── HTML helpers (for QTextBrowser / help dialog) ──────────────────────


