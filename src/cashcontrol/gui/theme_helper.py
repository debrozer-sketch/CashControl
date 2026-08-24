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


