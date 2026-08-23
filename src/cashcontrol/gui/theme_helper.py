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
_COLORS = {
    # ── Mimo «Операторский пульт» ──
    "bg_app":           ("#F5F6F8", "#12141A"),
    "bg_primary":       ("#F5F6F8", "#12141A"),
    "bg_surface":       ("#FFFFFF", "#1A1D25"),
    "bg_card":          ("#FFFFFF", "#1A1D25"),
    "bg_surface_alt":   ("#F0F1F4", "#151820"),
    "bg_secondary":     ("#F0F1F4", "#151820"),
    "bg_elevated":      ("#FFFFFF", "#1A1D25"),
    "bg_input":         ("#F8F9FA", "#13151B"),
    "bg_hover":         ("#E8EAEE", "#222630"),
    "bg_pressed":       ("#DCDFE4", "#1C2028"),
    "bg_ok":            ("#E8F5EE", "#142A1E"),
    "bg_slow":          ("#FFF8E6", "#2A2414"),
    "bg_timeout":       ("#FDE8E8", "#2A1616"),
    "bg_tertiary":      ("#F0F1F4", "#151820"),
    "bg_tooltip":       ("#FFFFFF", "#1A1D25"),
    "bg_dialog":        ("#F5F6F8", "#12141A"),
    "bg_selected":      ("#4A6FA5", "#6B9BD2"),
    "bg_warning":       ("#FFF8E6", "#2A2414"),
    "bg_info":          ("#F0F1F4", "#151820"),
    "bg_success":       ("#E8F5EE", "#142A1E"),
    "bg_danger":        ("#FDE8E8", "#2A1616"),
    "bg_table_alt":     ("#F0F1F4", "#151820"),
    "bg_code":          ("#F0F1F4", "#151820"),

    "text_primary":     ("#1A1D24", "#E8EAF0"),
    "text_secondary":   ("#5A6170", "#8A92A4"),
    "text_tertiary":    ("#9AA0AE", "#5A6478"),
    "text_muted":       ("#9AA0AE", "#5A6478"),
    "text_disabled":    ("#9AA0AE", "#5A6478"),
    "text_on_accent":   ("#FFFFFF", "#E8EAF0"),
    "text_inverse":     ("#FFFFFF", "#E8EAF0"),
    "text_link":        ("#4A6FA5", "#6B9BD2"),
    "text_heading":     ("#1A1D24", "#E8EAF0"),
    "text_code":        ("#1E2530", "#D4D8E0"),

    "border_default":   ("#D4D7DE", "#2A2F3A"),
    "border_primary":   ("#D4D7DE", "#2A2F3A"),
    "border_subtle":    ("#E4E6EB", "#222630"),
    "border_secondary": ("#E4E6EB", "#222630"),
    "border_input":     ("#D4D7DE", "#2A2F3A"),
    "border_focus":     ("#4A6FA5", "#6B9BD2"),
    "border_light":     ("#E4E6EB", "#222630"),
    "tab_hover_border": ("#D4D7DE", "#2A2F3A"),
    "control_border_bottom": ("#D4D7DE", "#2A2F3A"),

    "accent":           ("#4A6FA5", "#6B9BD2"),
    "accent_hover":     ("#3D5E8C", "#5A8AC0"),
    "accent_pressed":   ("#2E4A6E", "#4A7AAE"),
    "accent_text":      ("#4A6FA5", "#6B9BD2"),
    "accent_fill":      ("#4A6FA5", "#6B9BD2"),
    "accent_fill_hover": ("#3D5E8C", "#5A8AC0"),
    "accent_fill_pressed": ("#2E4A6E", "#4A7AAE"),
    "accent_subtle":    ("#E8EAEE", "#222630"),
    "accent_subtle_hover": ("#DCDFE4", "#1C2028"),
    "accent_light":     ("#E8EAEE", "#222630"),

    "ok":               ("#2D8A5E", "#4ADE80"),
    "slow":             ("#B8860B", "#FBBF24"),
    "timeout":          ("#C53030", "#F87171"),
    "unknown":          ("#8A92A4", "#5A6478"),
    "success":          ("#2D8A5E", "#4ADE80"),
    "warning":          ("#D97706", "#F59E0B"),
    "error":            ("#C53030", "#F87171"),
    "info":             ("#4A6FA5", "#6B9BD2"),
    "status_ok":        ("#2D8A5E", "#4ADE80"),
    "status_warn":      ("#B8860B", "#FBBF24"),
    "status_error":     ("#C53030", "#F87171"),
    "status_neutral":   ("#8A92A4", "#5A6478"),
    "ok_subtle":        ("#E8F5EE", "#142A1E"),
    "warn_subtle":      ("#FFF8E6", "#2A2414"),
    "error_subtle":     ("#FDE8E8", "#2A1616"),

    "control_fill":          ("#FFFFFF", "#1A1D25"),
    "control_fill_hover":    ("#E8EAEE", "#222630"),
    "control_fill_pressed":  ("#DCDFE4", "#1C2028"),
    "control_fill_disabled": ("#F0F1F4", "#151820"),
    "scrollbar_thumb":       ("#D4D7DE", "#2A2F3A"),
    "scrollbar_thumb_hover": ("#5A6170", "#8A92A4"),
    "scrollbar_hover":       ("#5A6170", "#8A92A4"),

    "mono_bg":          ("#F0F1F4", "#151820"),
    "mono_text":        ("#1E2530", "#D4D8E0"),
    "sql_bg":           ("#F8F9FA", "#13151B"),
    "sql_text":         ("#1E2530", "#D4D8E0"),
    "sql_keyword":      ("#4A6FA5", "#6B9BD2"),
    "sql_string":       ("#1E2530", "#D4D8E0"),
    "sql_number":       ("#3D5E8C", "#5A8AC0"),
    "sql_comment":      ("#9AA0AE", "#5A6478"),
    "sql_function":     ("#5A6170", "#8A92A4"),

    "separator":        ("#E4E6EB", "#222630"),

    "btn_danger_bg":    ("#FDE8E8", "#2A1616"),
    "btn_danger_hover": ("#C53030", "#F87171"),
    "btn_flat_hover":   ("#E8EAEE", "#222630"),
    "btn_cancel_bg":    ("#DCDFE4", "#1C2028"),

    "vnc_bg":           ("#12141A", "#12141A"),

    "table_header_bg":  ("#F0F1F4", "#151820"),
    "table_header_text": ("#1A1D24", "#E8EAF0"),

    "warning_border":   ("#B8860B", "#FBBF24"),
    "warning_text":     ("#B8860B", "#FBBF24"),
    "warning_bg":       ("#FFF8E6", "#2A2414"),
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


