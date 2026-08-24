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
# ── Brutalist Archive (ai/brutalist-archive.txt §2) ──
_COLORS = {
    "bg_primary":       ("#F2EDE4", "#1B1812"),
    "bg_secondary":     ("#E6DCCB", "#24201B"),
    "bg_card":          ("#FDF9F0", "#211D17"),
    "bg_surface":       ("#F7F2E6", "#1F1B16"),
    "bg_elevated":      ("#FFFDF5", "#25211C"),
    "bg_input":         ("#FFFDF5", "#211D17"),
    "bg_tertiary":      ("#EDE5D4", "#24201B"),
    "bg_hover":         ("#DDD0BF", "#2F2B23"),
    "bg_pressed":       ("#CCC0AE", "#3C362E"),
    "bg_selected":      ("#F0DBB8", "#3D2E1E"),
    "bg_disabled":      ("#DDD0BF", "#24201B"),
    "bg_tooltip":       ("#1B1812", "#F2EDE4"),
    "bg_dialog":        ("#FFFDF5", "#25211C"),
    "bg_warning":       ("#F8EAD6", "#3D2E1E"),
    "bg_info":          ("#E4E0D0", "#23201B"),
    "bg_success":       ("#DDE6D8", "#1C2A1D"),
    "bg_danger":        ("#F5DDD8", "#2B1818"),
    "bg_table_alt":     ("#EBE5D4", "#201C17"),
    "bg_code":          ("#1F1B16", "#0C0B08"),

    "text_primary":     ("#1B1812", "#F2EDE4"),
    "text_secondary":   ("#5A4F42", "#B5A898"),
    "text_tertiary":    ("#8C7E6E", "#7A6E5E"),
    "text_disabled":    ("#A89880", "#6E6050"),
    "text_on_accent":   ("#FFFDF5", "#FFFDF5"),
    "text_link":        ("#8F3B14", "#E88F6E"),
    "text_heading":     ("#1B1812", "#F2EDE4"),
    "text_code":        ("#4A7A4A", "#5A8A5A"),

    "border_primary":   ("#1B1812", "#5A5348"),
    "border_subtle":    ("#CCC6B8", "#3A342C"),
    "border_secondary": ("#8C7E6E", "#7A6E5E"),
    "border_input":     ("#B5A898", "#3A342C"),
    "border_focus":     ("#B83C1E", "#D46E54"),
    "tab_hover_border": ("#B83C1E", "#D46E54"),

    "accent":           ("#B83C1E", "#B83C1E"),
    "accent_hover":     ("#D46E54", "#D46E54"),
    "accent_pressed":   ("#8F2E15", "#8F2E15"),
    "accent_text":      ("#FFFDF5", "#FFFDF5"),
    "accent_fill":      ("#B83C1E", "#B83C1E"),
    "accent_fill_hover": ("#D46E54", "#D46E54"),
    "accent_fill_pressed": ("#8F2E15", "#8F2E15"),
    "accent_subtle":    ("#F5E0D4", "#3D2E1E"),
    "accent_subtle_hover": ("#EAD0B8", "#52391E"),
    "accent_light":     ("#F8EAD6", "#52391E"),

    "success":          ("#5A8A5A", "#6E8E6E"),
    "warning":          ("#C49A2E", "#D4A843"),
    "error":            ("#B83A2A", "#CC4A3A"),
    "info":             ("#7A7565", "#8A8578"),
    "slow":             ("#C49A2E", "#D4A843"),
    "timeout":          ("#B83A2A", "#CC4A3A"),
    "unknown":          ("#8C7E6E", "#7A6E5E"),
    "status_ok":        ("#5A8A5A", "#6E8E6E"),
    "status_warn":      ("#C49A2E", "#D4A843"),
    "status_error":     ("#B83A2A", "#CC4A3A"),
    "status_neutral":   ("#8C7E6E", "#7A6E5E"),
    "ok_subtle":        ("#DDE6D8", "#1C2A1D"),
    "warn_subtle":      ("#F8EAD6", "#3D2E1E"),
    "error_subtle":     ("#F5DDD8", "#2B1818"),
    "bg_ok":            ("#DDE6D8", "#1C2A1D"),
    "bg_slow":          ("#FFF8E6", "#2A2414"),
    "bg_timeout":       ("#F5DDD8", "#2B1818"),

    "separator":        ("#CCC6B8", "#3A342C"),
    "control_fill":          ("#DDD6C5", "#2F2B23"),
    "control_fill_hover":    ("#CCC6B8", "#3A342C"),
    "control_fill_pressed":  ("#B5A898", "#5A5348"),
    "control_fill_disabled": ("#DDD6C5", "#24201B"),
    "scrollbar_thumb":       ("#B5A898", "#5A5348"),
    "scrollbar_thumb_hover": ("#8C7E6E", "#7A6E5E"),

    "mono_bg":          ("#1F1B16", "#0C0B08"),
    "mono_text":        ("#F2EDE4", "#F2EDE4"),
    "sql_bg":           ("#1B1812", "#0C0B08"),
    "sql_text":         ("#F2EDE4", "#F2EDE4"),
    "sql_keyword":      ("#C49A2E", "#D4A843"),
    "sql_string":       ("#5A8A5A", "#6E8E6E"),
    "sql_number":       ("#D4A843", "#E0B880"),
    "sql_comment":      ("#8C7E6E", "#7A6E5E"),
    "sql_function":     ("#D4A843", "#E0B880"),

    "btn_danger_bg":    ("#B83A2A", "#CC4A3A"),
    "btn_danger_hover": ("#CC4A3A", "#DD5A4A"),
    "btn_flat_hover":   ("#DDD6C5", "#3A342C"),
    "btn_cancel_bg":    ("#DDD6C5", "#2F2B23"),

    "vnc_bg":           ("#0C0B08", "#0C0B08"),

    "table_header_bg":  ("#DDD6C5", "#2F2B23"),
    "table_header_text": ("#1B1812", "#F2EDE4"),

    "warning_border":   ("#C49A2E", "#D4A843"),
    "warning_text":     ("#7A5E20", "#C49A2E"),
    "warning_bg":       ("#F8EAD6", "#3D2E1E"),

    "border_light":     ("#CCC6B8", "#3A342C"),
    "control_border_bottom": ("#B5A898", "#3A342C"),
    "bg_app":           ("#F2EDE4", "#1B1812"),
    "bg_primary_soft":  ("#F2EDE4", "#1B1812"),
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


