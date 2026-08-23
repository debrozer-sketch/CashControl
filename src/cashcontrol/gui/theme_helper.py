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
_COLORS = {
    # Backgrounds
    "bg_primary":       ("#ffffff", "#202020"),
    "bg_secondary":     ("#f3f3f3", "#2b2b2b"),
    "bg_tertiary":      ("#e8edf5", "#333333"),
    "bg_surface":       ("#ffffff", "#2b2b2b"),
    "bg_hover":         ("#e0e0e0", "#3d3d3d"),
    "bg_pressed":       ("#d0d0d0", "#1a1a1a"),
    "bg_input":         ("#ffffff", "#2b2b2b"),
    "bg_code":          ("#f5f5f5", "#1e1e1e"),
    "bg_tooltip":       ("#ffffff", "#2b2b2b"),
    "bg_dialog":        ("#ffffff", "#202020"),
    "bg_selected":      ("#0078d4", "#0078d4"),
    "bg_warning":       ("#fff8e1", "#3d3000"),
    "bg_info":          ("#e3f2fd", "#0d2137"),
    "bg_success":       ("#e8f5e9", "#0d2b0d"),
    "bg_danger":        ("#fce4ec", "#3d0a0a"),
    "bg_table_alt":     ("#f4f6f9", "#2f2f2f"),

    # Text
    "text_primary":     ("#1a1a2e", "#e0e0e0"),
    "text_secondary":   ("#555555", "#aaaaaa"),
    "text_tertiary":    ("#888888", "#666666"),
    "text_on_accent":   ("#ffffff", "#ffffff"),
    "text_link":        ("#1565c0", "#5ba3e6"),
    "text_heading":     ("#1a1a2e", "#e0e0e0"),
    "text_code":        ("#333333", "#d4d4d4"),

    # Borders
    "border_primary":   ("#d0d0d0", "#3f3f3f"),
    "border_secondary": ("#e0e0e0", "#333333"),
    "border_input":     ("#c0c0c0", "#3f3f3f"),
    "border_focus":     ("#0078d4", "#0078d4"),
    "tab_hover_border": ("#909090", "#555555"),

    # Accent
    "accent":           ("#0078d4", "#0078d4"),
    "accent_hover":     ("#106ebe", "#1a8ae6"),
    "accent_light":     ("#e6f1fb", "#0a3a6b"),

    # Status
    "success":          ("#4caf50", "#66bb6a"),
    "error":            ("#f44336", "#ef5350"),
    "warning":          ("#ff9800", "#ffa726"),
    "info":             ("#2196f3", "#42a5f5"),

    # Separator
    "separator":        ("#d0d0d0", "#3f3f3f"),

    # Specific components
    "btn_danger_bg":    ("#d32f2f", "#c62828"),
    "btn_danger_hover": ("#b71c1c", "#a31515"),
    "btn_flat_hover":   ("#e8edf5", "#3d3d3d"),
    "btn_cancel_bg":    ("#e0e0e0", "#3d3d3d"),

    # VNC preview
    "vnc_bg":           ("#1a1a2e", "#1a1a2e"),

    # Table header
    "table_header_bg":  ("#e4eaf5", "#333333"),
    "table_header_text":("#1a1a2e", "#e0e0e0"),

    # Warning box (help dialog, notes)
    "warning_border":   ("#ffb300", "#ffb300"),
    "warning_text":     ("#795548", "#d4a574"),
    "warning_bg":       ("#fff8e1", "#3d3000"),
}


# ── Fluent Data Surface (ai/gpt-5.6-terra-xhigh.txt §7.1) ─────────────

_COLORS.update({
    "transparent": ("transparent", "transparent"),

    "bg_primary":       ("#F7F8FA", "#1B1D21"),
    "bg_sidebar":       ("#F1F3F6", "#202329"),
    "bg_surface":       ("#FFFFFF", "#272A30"),
    "bg_surface_alt":   ("#EEF1F5", "#2E3239"),
    "bg_raised":        ("#FFFFFF", "#333840"),
    "bg_hover":         ("#E6EEF8", "#353D48"),
    "bg_pressed":       ("#D4E4F5", "#414C5B"),
    "bg_selected":      ("#DDEBFA", "#173B5B"),
    "bg_disabled":      ("#ECEEF1", "#292D33"),
    "bg_input":         ("#FFFFFF", "#22262C"),
    "bg_code":          ("#F5F7FA", "#1D2127"),

    "text_primary":     ("#1B1F23", "#F2F4F7"),
    "text_secondary":   ("#53606E", "#C7CFD9"),
    "text_tertiary":    ("#66717E", "#A5AFBC"),
    "text_disabled":    ("#5D6773", "#AAB4C0"),

    "accent":           ("#005FB8", "#58A6FF"),
    "accent_hover":     ("#004C97", "#7DBCFF"),
    "accent_pressed":   ("#003B75", "#3E92E6"),
    "accent_subtle":    ("#E1EFFB", "#173A5B"),
    "text_on_accent":   ("#FFFFFF", "#081522"),

    "border_primary":   ("#CDD3DA", "#484E58"),
    "border_subtle":    ("#E3E7EB", "#363C45"),
    "border_strong":    ("#AAB3BD", "#67717D"),
    "border_focus":     ("#0F6CBD", "#78B9FF"),

    "success":          ("#0F6B3C", "#57D38C"),
    "success_subtle":   ("#E5F4EA", "#123A2B"),
    "warning":          ("#875900", "#F4C64E"),
    "warning_subtle":   ("#FFF3D6", "#443713"),
    "danger":           ("#B42318", "#FF8983"),
    "danger_hover":     ("#8F1B13", "#FFAAA5"),
    "danger_pressed":   ("#75150F", "#E96E68"),
    "danger_subtle":    ("#FDE9E7", "#4E1E1C"),
    "text_on_danger":   ("#FFFFFF", "#250605"),
    "info":             ("#005FB8", "#70B5FF"),
    "info_subtle":      ("#E1EFFB", "#173A5B"),

    "link":             ("#005FB8", "#70B5FF"),
    "link_hover":       ("#004C97", "#9ACAFF"),

    "scrollbar":        ("#B7C0CA", "#606A77"),
    "scrollbar_hover":  ("#8D99A6", "#8793A2"),

    "syntax_keyword":   ("#6F2DBD", "#C792EA"),
    "syntax_string":    ("#0F6B3C", "#A5E075"),
    "syntax_number":    ("#005FB8", "#82AAFF"),
    "syntax_comment":   ("#66717E", "#8892A0"),
    "syntax_operator":  ("#9A4D00", "#FFB86C"),
})

# Алиасы legacy-ключей → новая палитра (старый код продолжает работать)
_COLORS.update({
    "bg_secondary": _COLORS["bg_sidebar"],
    "bg_card": _COLORS["bg_surface"],
    "bg_elevated": _COLORS["bg_raised"],
    "bg_tooltip": _COLORS["bg_raised"],
    "bg_dialog": _COLORS["bg_surface"],
    "bg_tertiary": _COLORS["bg_surface_alt"],
    "bg_table_alt": _COLORS["bg_surface_alt"],
    "bg_info": _COLORS["info_subtle"],
    "bg_success": _COLORS["success_subtle"],
    "bg_warning": _COLORS["warning_subtle"],
    "bg_danger": _COLORS["danger_subtle"],
    "text_heading": _COLORS["text_primary"],
    "text_code": _COLORS["text_primary"],
    "text_link": _COLORS["link"],
    "accent_text": _COLORS["link"],
    "accent_fill": _COLORS["accent"],
    "accent_fill_hover": _COLORS["accent_hover"],
    "accent_fill_pressed": _COLORS["accent_pressed"],
    "accent_light": _COLORS["accent_subtle"],
    "status_ok": _COLORS["success"],
    "status_warn": _COLORS["warning"],
    "status_error": _COLORS["danger"],
    "status_neutral": _COLORS["text_tertiary"],
    "ok_subtle": _COLORS["success_subtle"],
    "warn_subtle": _COLORS["warning_subtle"],
    "error_subtle": _COLORS["danger_subtle"],
    "border_secondary": _COLORS["border_subtle"],
    "border_input": _COLORS["border_primary"],
    "border_light": _COLORS["border_subtle"],
    "tab_hover_border": _COLORS["border_strong"],
    "control_border_bottom": _COLORS["border_primary"],
    "control_fill": ("#FBFBFB", "rgba(255,255,255,15)"),
    "control_fill_hover": _COLORS["bg_hover"],
    "control_fill_pressed": _COLORS["bg_pressed"],
    "control_fill_disabled": _COLORS["bg_disabled"],
    "scrollbar_thumb": _COLORS["scrollbar"],
    "scrollbar_thumb_hover": _COLORS["scrollbar_hover"],
    "sql_bg": _COLORS["bg_code"],
    "sql_text": _COLORS["text_primary"],
    "sql_keyword": _COLORS["syntax_keyword"],
    "sql_string": _COLORS["syntax_string"],
    "sql_number": _COLORS["syntax_number"],
    "sql_comment": _COLORS["syntax_comment"],
    "sql_function": _COLORS["accent"],
    "separator": _COLORS["border_subtle"],
    "btn_danger_bg": _COLORS["danger"],
    "btn_danger_hover": _COLORS["danger_hover"],
    "btn_flat_hover": _COLORS["bg_hover"],
    "btn_cancel_bg": _COLORS["bg_pressed"],
    "table_header_bg": _COLORS["bg_surface_alt"],
    "table_header_text": _COLORS["text_secondary"],
})


_TOKEN_RE = re.compile(r"@([a-z][a-z0-9_]*)")


def color_for_theme(name: str, is_dark: bool) -> str:
    """Цвет токена для конкретной темы без изменения текущего API color()."""
    return _COLORS[name][1 if is_dark else 0]


def render_theme_tokens(template: str, is_dark: bool) -> str:
    """Подставляет @accent, @bg_surface и другие токены в QSS/CSS."""

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in _COLORS:
            raise KeyError(f"Unknown theme token: {key}")
        return color_for_theme(key, is_dark)

    return _TOKEN_RE.sub(replace, template)


def set_visual_role(widget, role: str | None = None, **properties) -> None:
    """Только визуальные dynamic-properties, без изменения логики виджета."""
    if role is not None:
        widget.setProperty("ccRole", role)

    for key, value in properties.items():
        qss_key = f"cc{key[:1].upper()}{key[1:]}"
        if isinstance(value, bool):
            value = "true" if value else "false"
        widget.setProperty(qss_key, str(value))

    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


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


