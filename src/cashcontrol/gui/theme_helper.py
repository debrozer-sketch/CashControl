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
    # Backgrounds
    "bg_app":           ("#f3f3f3", "#202020"),
    "bg_primary":       ("#f3f3f3", "#202020"),
    "bg_secondary":     ("#fafafa", "#272727"),
    "bg_card":          ("#ffffff", "#2d2d2d"),
    "bg_surface":       ("#ffffff", "#2d2d2d"),
    "bg_surface_hover": ("#f9f9f9", "#383838"),
    "bg_elevated":      ("#f9f9f9", "#2d2d2d"),
    "bg_tertiary":      ("#e8edf5", "#333333"),
    "bg_hover":         ("#e0e0e0", "#3d3d3d"),
    "bg_pressed":       ("#d0d0d0", "#1a1a1a"),
    "bg_input":         ("#ffffff", "#2d2d2d"),
    "bg_code":          ("#f5f5f5", "#1e1e1e"),
    "bg_tooltip":       ("#ffffff", "#2b2b2b"),
    "bg_dialog":        ("#ffffff", "#202020"),
    "bg_selected":      ("#0067c0", "#4cc2ff"),
    "bg_warning":       ("#fff8e1", "#3d3000"),
    "bg_info":          ("#e3f2fd", "#0d2137"),
    "bg_success":       ("#e8f5e9", "#0d2b0d"),
    "bg_danger":        ("#fce4ec", "#3d0a0a"),
    "bg_table_alt":     ("#f9f9f9", "#383838"),

    # Text
    "text_primary":     ("#1a1a1a", "#ffffff"),
    "text_secondary":   ("#616161", "#a0a0a0"),
    "text_tertiary":    ("#767676", "#9d9d9d"),
    "text_disabled":    ("#a6a6a6", "#6d6d6d"),
    "text_on_accent":   ("#ffffff", "#1b1b1b"),
    "text_link":        ("#0067c0", "#4cc2ff"),
    "text_heading":     ("#1a1a1a", "#ffffff"),
    "text_code":        ("#333333", "#d4d4d4"),

    # Borders
    "border_primary":   ("#d0d0d0", "#3f3f3f"),
    "border_light":     ("#e5e5e5", "#434343"),
    "border_subtle":    ("#e5e5e5", "#434343"),
    "border_secondary": ("#e0e0e0", "#333333"),
    "border_input":     ("#c0c0c0", "#3f3f3f"),
    "border_focus":     ("#0067c0", "#4cc2ff"),
    "tab_hover_border": ("#909090", "#555555"),
    "control_border_bottom": ("#8a8a8a", "#9a9a9a"),

    # Accent
    "accent":           ("#0067c0", "#4cc2ff"),
    "accent_text":      ("#0067c0", "#4cc2ff"),
    "accent_fill":      ("#0067c0", "#4cc2ff"),
    "accent_fill_hover": ("#00549e", "#45b1e8"),
    "accent_fill_pressed": ("#00549e", "#45b1e8"),
    "accent_subtle":    ("rgba(0,103,192,38)", "rgba(76,194,255,48)"),
    "accent_subtle_hover": ("rgba(0,103,192,60)", "rgba(76,194,255,70)"),
    "accent_hover":     ("#00549e", "#45b1e8"),
    "accent_light":     ("#e6f1fb", "#0a3a6b"),

    # Status
    "status_ok":        ("#0f7b0f", "#6ccb5f"),
    "status_slow":      ("#9d5d00", "#fce100"),
    "status_fail":      ("#c42b1c", "#ff99a4"),
    "status_neutral":   ("#6b6b6b", "#9d9d9d"),
    "success":          ("#0f7b0f", "#6ccb5f"),
    "warning":          ("#9d5d00", "#fce100"),
    "error":            ("#c42b1c", "#ff99a4"),
    "info":             ("#2196f3", "#42a5f5"),
    "ok_subtle":        ("#dff6dd", "#0e2b12"),
    "warn_subtle":      ("#fff4ce", "#3a2d0c"),
    "error_subtle":     ("#fde7e9", "#40161a"),

    # Controls
    "control_fill":          ("#fbfbfb", "rgba(255,255,255,15)"),
    "control_fill_hover":    ("#f9f9f9", "rgba(255,255,255,23)"),
    "control_fill_pressed":  ("#eeeeee", "rgba(255,255,255,10)"),
    "control_fill_disabled": ("#f0f0f0", "rgba(255,255,255,8)"),
    "scrollbar_thumb":       ("rgba(0,0,0,87)", "rgba(255,255,255,82)"),
    "scrollbar_thumb_hover": ("rgba(0,0,0,128)", "rgba(255,255,255,128)"),

    # SQL console / logs
    "sql_bg":           ("#ffffff", "#1b1b1b"),
    "sql_text":         ("#1b1b1b", "#d4d4d4"),
    "sql_keyword":      ("#0451a5", "#569cd6"),
    "sql_string":       ("#a31515", "#ce9178"),
    "sql_number":       ("#098658", "#b5cea8"),
    "sql_comment":      ("#008000", "#6a9955"),
    "sql_function":     ("#795e26", "#dcdcaa"),

    # Separator
    "separator":        ("#d0d0d0", "#3f3f3f"),

    # Specific components
    "btn_danger_bg":    ("#d32f2f", "#c62828"),
    "btn_danger_hover": ("#b71c1c", "#a31515"),
    "btn_flat_hover":   ("#f9f9f9", "#3d3d3d"),
    "btn_cancel_bg":    ("#e0e0e0", "#3d3d3d"),

    # VNC preview
    "vnc_bg":           ("#1a1a2e", "#1a1a2e"),

    # Table header
    "table_header_bg":  ("#f3f3f3", "#202020"),
    "table_header_text":("#616161", "#a0a0a0"),

    # Warning box (help dialog, notes)
    "warning_border":   ("#ffb300", "#ffb300"),
    "warning_text":     ("#795548", "#d4a574"),
    "warning_bg":       ("#fff8e1", "#3d3000"),
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


