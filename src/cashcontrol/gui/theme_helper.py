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
# ── Табло и эмаль (ai/tablo-emal.txt §2) ──
_COLORS = {
    "bg_primary":       ("#E8E6DE", "#0D171D"),
    "bg_secondary":     ("#DCD9CF", "#091218"),
    "bg_card":          ("#FFFFFF", "#142330"),
    "bg_surface":       ("#F4F2EC", "#101C25"),
    "bg_elevated":      ("#FFFFFF", "#1A2C3A"),
    "bg_input":         ("#FFFFFF", "#0A141A"),
    "bg_tertiary":      ("#CFCBBE", "#1E3243"),
    "bg_hover":         ("#E2DFD4", "#1B2E3C"),
    "bg_pressed":       ("#CFCBBE", "#24394A"),
    "bg_selected":      ("#FBE0CF", "#43291B"),
    "bg_disabled":      ("#E5E3DB", "#121D25"),
    "bg_tooltip":       ("#141414", "#EDE9DE"),
    "bg_dialog":        ("#F7F5EF", "#12202B"),
    "bg_warning":       ("#FDF0CC", "#3B2E10"),
    "bg_info":          ("#E1EAF0", "#13293D"),
    "bg_success":       ("#DDEEDF", "#10301E"),
    "bg_danger":        ("#FADFD8", "#3B1815"),
    "bg_table_alt":     ("#F2F0E9", "#101E28"),
    "bg_code":          ("#F6F4EC", "#081016"),

    "text_primary":     ("#141414", "#EDEAE0"),
    "text_secondary":   ("#4A4740", "#ADB8BF"),
    "text_tertiary":    ("#6E6A60", "#8B99A3"),
    "text_disabled":    ("#A29E93", "#5E6C76"),
    "text_on_accent":   ("#FFFFFF", "#14100C"),
    "text_link":        ("#14458C", "#7FB2E8"),
    "text_heading":     ("#000000", "#FFFFFF"),
    "text_code":        ("#1B1B1B", "#E4E0D3"),

    "border_primary":   ("#1A1A1A", "#3A5567"),
    "border_subtle":    ("#C6C2B5", "#22384A"),
    "border_secondary": ("#4A4740", "#547189"),
    "border_input":     ("#1A1A1A", "#3A5567"),
    "border_focus":     ("#C4400F", "#FF8A3D"),
    "tab_hover_border": ("#C4400F", "#FF8A3D"),

    "accent":           ("#C4400F", "#FF8A3D"),
    "accent_hover":     ("#D8541D", "#FFA062"),
    "accent_pressed":   ("#9E3208", "#E16F26"),
    "accent_text":      ("#A83500", "#FFA062"),
    "accent_fill":      ("#C4400F", "#FF8A3D"),
    "accent_fill_hover": ("#D8541D", "#FFA062"),
    "accent_fill_pressed": ("#9E3208", "#E16F26"),
    "accent_subtle":    ("#FBE3D5", "#3A2415"),
    "accent_subtle_hover": ("#F7D3BE", "#4A2E19"),
    "accent_light":     ("#EFA37F", "#A05A2C"),

    "success":          ("#1E7A3C", "#5FC27E"),
    "warning":          ("#8A6100", "#E8B23C"),
    "error":            ("#B0231A", "#FF7A68"),
    "info":             ("#14458C", "#6FA8DC"),
    "separator":        ("#C6C2B5", "#22384A"),
    "control_fill":          ("#FFFFFF", "#172836"),
    "control_fill_hover":    ("#F1EEE6", "#1F3446"),
    "control_fill_pressed":  ("#DFDBD0", "#0F1D27"),
    "control_fill_disabled": ("#E5E3DB", "#121D25"),
    "scrollbar_thumb":       ("#9C9789", "#33526A"),
    "scrollbar_thumb_hover": ("#6E6A60", "#4A7089"),

    "sql_bg":           ("#FDFCF8", "#081016"),
    "sql_text":         ("#141414", "#E4E0D3"),
    "sql_keyword":      ("#A83500", "#FFA062"),
    "sql_string":       ("#1E7A3C", "#8FD6A0"),
    "sql_number":       ("#14458C", "#7FB2E8"),
    "sql_comment":      ("#7A766B", "#6B7C88"),
    "sql_function":     ("#7A2A8C", "#D79BE8"),

    "btn_danger_bg":    ("#B0231A", "#A32E22"),
    "btn_danger_hover": ("#8E1A12", "#C43B2C"),
    "btn_flat_hover":   ("#E2DFD4", "#1B2E3C"),
    "btn_cancel_bg":    ("#E5E3DB", "#172836"),
    "vnc_bg":           ("#0B0E10", "#05090C"),
    "table_header_bg":  ("#141414", "#DCE3E7"),
    "table_header_text": ("#FFFFFF", "#0D1A21"),
    "warning_border":   ("#C79A16", "#7A5E1C"),
    "warning_text":     ("#6E4E00", "#F0C465"),
    "warning_bg":       ("#FDF0CC", "#3B2E10"),

    "route_pos":        ("#C4400F", "#FF8A3D"),
    "route_hw":         ("#14458C", "#6FA8DC"),
    "route_misc":       ("#7A2A8C", "#C48BE0"),
    "route_idle":       ("#9C9789", "#4A7089"),
    "rail":             ("#1A1A1A", "#3A5567"),

    "unknown":          ("#6E6A60", "#8B99A3"),
    "bg_app":           ("#E8E6DE", "#0D171D"),
    "border_light":     ("#C6C2B5", "#22384A"),
    "control_border_bottom": ("#1A1A1A", "#3A5567"),

    "status_ok":        ("#1E7A3C", "#5FC27E"),
    "status_warn":      ("#8A6100", "#E8B23C"),
    "status_error":     ("#B0231A", "#FF7A68"),
    "status_neutral":   ("#6E6A60", "#8B99A3"),
    "ok_subtle":        ("#DDEEDF", "#10301E"),
    "warn_subtle":      ("#FDF0CC", "#3B2E10"),
    "error_subtle":     ("#FADFD8", "#3B1815"),
    "bg_ok":            ("#DDEEDF", "#10301E"),
    "bg_slow":          ("#FDF0CC", "#3B2E10"),
    "bg_timeout":       ("#FADFD8", "#3B1815"),

    "scrollbar":        ("#9C9789", "#33526A"),
    "scrollbar_hover":  ("#6E6A60", "#4A7089"),
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


