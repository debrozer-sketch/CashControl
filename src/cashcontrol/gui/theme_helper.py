"""Centralized theme helpers for CashControl GUI.

Provides dynamic color resolution based on current qfluentwidgets theme.
All GUI modules should use these helpers instead of hardcoding hex colors.
"""

from __future__ import annotations


def is_dark() -> bool:
    """Return True if current qfluentwidgets theme is dark."""
    try:
        from qfluentwidgets import isDarkTheme
        return isDarkTheme()
    except Exception:
        return False


# ── Color palette ──────────────────────────────────────────────────────

# Semantic color pairs: (light_value, dark_value)
# ── Calm Telemetry (ai/gpt-5.6-sol-medium.txt §5.1) ──
_COLORS = {
    "bg_app":             ("#EEF2F6", "#10151D"),
    "bg_primary":         ("#EEF2F6", "#10151D"),
    "bg_sidebar":         ("#172235", "#0B1017"),
    "bg_surface":         ("#FFFFFF", "#171E28"),
    "bg_surface_raised":  ("#F8FAFC", "#1C2531"),
    "bg_surface_sunken":  ("#E7EDF3", "#0D1219"),
    "bg_hover":           ("#E8EEF7", "#222D3A"),
    "bg_pressed":         ("#DCE5F1", "#293646"),
    "bg_selected":        ("#DCE8FC", "#243856"),
    "bg_disabled":        ("#E9EDF2", "#171D25"),

    "text_primary":       ("#182230", "#E7EDF5"),
    "text_secondary":     ("#536273", "#AAB6C5"),
    "text_muted":         ("#758397", "#7F8C9F"),
    "text_disabled":      ("#98A4B3", "#596676"),
    "text_inverse":       ("#FFFFFF", "#0D1420"),
    "text_sidebar":       ("#DCE7F7", "#C8D4E5"),

    "border":             ("#CDD6E1", "#303B49"),
    "border_subtle":      ("#E0E6ED", "#25303C"),
    "border_strong":      ("#AEBAC8", "#465467"),
    "focus":              ("#2864DC", "#70A0FF"),

    "accent":             ("#2864DC", "#70A0FF"),
    "accent_hover":       ("#1F55C2", "#8BB2FF"),
    "accent_pressed":     ("#19459E", "#5C8EEB"),
    "accent_soft":        ("#E0EAFC", "#233754"),

    "success":            ("#167A56", "#4ACA91"),
    "success_soft":       ("#E2F3EC", "#17392E"),
    "warning":            ("#9A6100", "#F0B64A"),
    "warning_soft":       ("#FFF0CF", "#40331A"),
    "danger":             ("#BE3945", "#FF737D"),
    "error":              ("#BE3945", "#FF737D"),
    "danger_hover":       ("#A72F3B", "#FF929A"),
    "danger_soft":        ("#FBE3E6", "#442329"),
    "info":               ("#18749A", "#59BCE5"),
    "info_soft":          ("#DFF1F8", "#173541"),
    "ping_unknown":       ("#8491A2", "#6F7D8F"),

    "code_bg":            ("#F1F4F8", "#0C1118"),
    "code_text":          ("#233043", "#D8E3F1"),
    "code_keyword":       ("#7557C2", "#C29BFF"),
    "code_string":        ("#A34E13", "#F2A86F"),
    "code_comment":       ("#708090", "#748397"),

    "table_header":       ("#E8EDF3", "#1D2632"),
    "table_alt":          ("#F7F9FB", "#141B24"),
    "table_grid":         ("#DCE3EB", "#293542"),

    "scroll_track":       ("#E9EDF2", "#131A23"),
    "scroll_thumb":       ("#AEB9C6", "#485668"),
    "scroll_thumb_hover": ("#8F9EAE", "#607188"),

    "tooltip_bg":         ("#172235", "#E7EDF5"),
    "tooltip_text":       ("#F7FAFE", "#131A23"),
    "vnc_bg":             ("#121821", "#080B10"),
    "overlay_scrim":      ("#D9E0E8", "#080C12"),
}

# Алиасы legacy-ключей
_COLORS.update({
    "bg_secondary": _COLORS["bg_surface_sunken"],
    "bg_card": _COLORS["bg_surface"],
    "bg_elevated": _COLORS["bg_surface_raised"],
    "bg_input": _COLORS["bg_surface_sunken"],
    "bg_tertiary": _COLORS["bg_surface_sunken"],
    "bg_tooltip": _COLORS["tooltip_bg"],
    "bg_dialog": _COLORS["bg_surface"],
    "bg_warning": _COLORS["warning_soft"],
    "bg_info": _COLORS["info_soft"],
    "bg_success": _COLORS["success_soft"],
    "bg_danger": _COLORS["danger_soft"],
    "bg_table_alt": _COLORS["table_alt"],
    "bg_code": _COLORS["code_bg"],
    "text_tertiary": _COLORS["text_muted"],
    "text_on_accent": _COLORS["text_inverse"],
    "text_link": _COLORS["accent"],
    "text_heading": _COLORS["text_primary"],
    "text_code": _COLORS["code_text"],
    "border_primary": _COLORS["border"],
    "border_secondary": _COLORS["border_subtle"],
    "border_input": _COLORS["border"],
    "border_light": _COLORS["border_subtle"],
    "border_focus": _COLORS["focus"],
    "tab_hover_border": _COLORS["border_strong"],
    "control_border_bottom": _COLORS["border"],
    "accent_text": _COLORS["accent"],
    "accent_fill": _COLORS["accent"],
    "accent_fill_hover": _COLORS["accent_hover"],
    "accent_fill_pressed": _COLORS["accent_pressed"],
    "accent_subtle": _COLORS["accent_soft"],
    "accent_subtle_hover": _COLORS["bg_hover"],
    "accent_light": _COLORS["accent_soft"],
    "status_ok": _COLORS["success"],
    "status_warn": _COLORS["warning"],
    "status_error": _COLORS["danger"],
    "status_neutral": _COLORS["ping_unknown"],
    "ok_subtle": _COLORS["success_soft"],
    "warn_subtle": _COLORS["warning_soft"],
    "error_subtle": _COLORS["danger_soft"],
    "bg_ok": _COLORS["success_soft"],
    "bg_slow": _COLORS["warning_soft"],
    "bg_timeout": _COLORS["danger_soft"],
    "control_fill": _COLORS["bg_surface"],
    "control_fill_hover": _COLORS["bg_hover"],
    "control_fill_pressed": _COLORS["bg_pressed"],
    "control_fill_disabled": _COLORS["bg_disabled"],
    "scrollbar_thumb": _COLORS["scroll_thumb"],
    "scrollbar_thumb_hover": _COLORS["scroll_thumb_hover"],
    "scrollbar_hover": _COLORS["scroll_thumb_hover"],
    "sql_bg": _COLORS["code_bg"],
    "sql_text": _COLORS["code_text"],
    "sql_keyword": _COLORS["code_keyword"],
    "sql_string": _COLORS["code_string"],
    "sql_number": _COLORS["accent"],
    "sql_comment": _COLORS["code_comment"],
    "sql_function": _COLORS["text_secondary"],
    "separator": _COLORS["border_subtle"],
    "btn_danger_bg": _COLORS["danger_soft"],
    "btn_danger_hover": _COLORS["danger_hover"],
    "btn_flat_hover": _COLORS["bg_hover"],
    "btn_cancel_bg": _COLORS["bg_pressed"],
    "table_header_bg": _COLORS["table_header"],
    "table_header_text": _COLORS["text_secondary"],
    "warning_border": _COLORS["warning"],
    "warning_text": _COLORS["warning"],
    "warning_bg": _COLORS["warning_soft"],
})



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


def set_visual_property(widget, name: str, value) -> None:
    """Динамическое property с гарантированным repolish."""
    if widget.property(name) == value:
        return
    widget.setProperty(name, value)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


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


