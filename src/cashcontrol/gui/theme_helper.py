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
# --- token map: name -> (light, dark) ---
_COLORS = {
    "bg.app":              ("#E8ECF1", "#0F1218"),
    "bg.sidebar":          ("#DDE3EB", "#0A0D12"),
    "bg.surface":          ("#F4F6F9", "#171C25"),
    "bg.surface2":         ("#FFFFFF", "#1E2530"),
    "bg.sunken":           ("#DCE2EA", "#0C0F14"),
    "bg.overlay":          ("#F0F3F7", "#252D3A"),
    "bg.hover":            ("#D5DCE6", "#2A3342"),
    "bg.pressed":          ("#C5CEDA", "#343E50"),
    "bg.selected":         ("#D0E8E6", "#1A3335"),
    "bg.tab":              ("#E2E7EE", "#141922"),
    "bg.tab.active":       ("#FFFFFF", "#1E2530"),
    "border.subtle":       ("#C9D1DC", "#2C3544"),
    "border.strong":       ("#A8B4C4", "#3D4A5C"),
    "border.focus":        ("#2A9B8F", "#3DBDB0"),
    "text.primary":        ("#1A2332", "#E8EDF5"),
    "text.secondary":      ("#5A6A7E", "#8B9BB0"),
    "text.tertiary":       ("#7A8B9E", "#6B7C90"),
    "text.inverse":        ("#FFFFFF", "#0F1218"),
    "text.link":           ("#1B7A72", "#5ED4C8"),
    "accent.default":      ("#2A9B8F", "#3DBDB0"),
    "accent.hover":        ("#238A7F", "#4FCBBF"),
    "accent.pressed":      ("#1C7369", "#2A9B8F"),
    "accent.muted":        ("#D0E8E6", "#1A3335"),
    "semantic.ok":         ("#1F8A4C", "#3DD68C"),
    "semantic.ok.muted":   ("#D8F3E4", "#143D28"),
    "semantic.slow":       ("#C48A00", "#E6B84D"),
    "semantic.slow.muted": ("#F8EDD0", "#3D3010"),
    "semantic.err":        ("#C43C3C", "#F07178"),
    "semantic.err.muted":  ("#F8D6D6", "#3D181A"),
    "semantic.info":       ("#2B6FCB", "#6AA8FF"),
    "semantic.info.muted": ("#D6E6FA", "#152A45"),
    "semantic.unknown":    ("#8A96A8", "#6B7A8F"),
    "data.mono":           ("#1A2332", "#D2DAE6"),
    "data.key":            ("#5A6A7E", "#8B9BB0"),
    "scrollbar":           ("#B0BCCB", "#3A4658"),
    "scrollbar.hover":     ("#8FA0B5", "#506178"),
    "vnc.letterbox":       ("#0A0C10", "#000000"),
    "danger.btn":          ("#B83535", "#D45050"),
    "danger.btn.hover":    ("#9E2C2C", "#E06868"),
    "grid.line":           ("#E2E7EE", "#252D3A"),
    "grid.alt":            ("#F0F3F7", "#1A2029"),
    "code.bg":             ("#F0F3F7", "#12171F"),
    "code.keyword":        ("#0B5FFF", "#79B8FF"),
    "code.string":         ("#1F8A4C", "#7EE787"),
    "code.number":         ("#A35C00", "#FFB060"),
    "code.comment":        ("#7A8B9E", "#6B7C90"),
}

# Алиасы legacy underscore-ключей → Signal Deck
_COLORS.update({
    "bg_secondary": _COLORS["bg.sidebar"],
    "bg_card": _COLORS["bg.surface2"],
    "bg_elevated": _COLORS["bg.overlay"],
    "bg_input": _COLORS["bg.sunken"],
    "bg_tertiary": _COLORS["bg.tab"],
    "bg_tooltip": _COLORS["bg.overlay"],
    "bg_dialog": _COLORS["bg.surface2"],
    "bg_warning": _COLORS["semantic.slow.muted"],
    "bg_info": _COLORS["semantic.info.muted"],
    "bg_success": _COLORS["semantic.ok.muted"],
    "bg_danger": _COLORS["semantic.err.muted"],
    "bg_table_alt": _COLORS["grid.alt"],
    "bg_code": _COLORS["code.bg"],
    "text_disabled": _COLORS["text.tertiary"],
    "text_heading": _COLORS["text.primary"],
    "text_code": _COLORS["data.mono"],
    "border_primary": _COLORS["border.subtle"],
    "border_secondary": _COLORS["border.subtle"],
    "border_input": _COLORS["border.subtle"],
    "border_light": _COLORS["border.subtle"],
    "tab_hover_border": _COLORS["border.strong"],
    "control_border_bottom": _COLORS["border.subtle"],
    "accent": _COLORS["accent.default"],
    "accent_text": _COLORS["text.link"],
    "accent_fill": _COLORS["accent.default"],
    "accent_fill_hover": _COLORS["accent.hover"],
    "accent_fill_pressed": _COLORS["accent.pressed"],
    "accent_subtle": _COLORS["accent.muted"],
    "accent_subtle_hover": _COLORS["bg.hover"],
    "accent_light": _COLORS["accent.muted"],
    "success": _COLORS["semantic.ok"],
    "warning": _COLORS["semantic.slow"],
    "error": _COLORS["semantic.err"],
    "info": _COLORS["semantic.info"],
    "status_ok": _COLORS["semantic.ok"],
    "status_warn": _COLORS["semantic.slow"],
    "status_error": _COLORS["semantic.err"],
    "status_neutral": _COLORS["semantic.unknown"],
    "ok_subtle": _COLORS["semantic.ok.muted"],
    "warn_subtle": _COLORS["semantic.slow.muted"],
    "error_subtle": _COLORS["semantic.err.muted"],
    "bg_ok": _COLORS["semantic.ok.muted"],
    "bg_slow": _COLORS["semantic.slow.muted"],
    "bg_timeout": _COLORS["semantic.err.muted"],
    "control_fill": _COLORS["bg.surface2"],
    "control_fill_hover": _COLORS["bg.hover"],
    "control_fill_pressed": _COLORS["bg.pressed"],
    "control_fill_disabled": _COLORS["bg.surface"],
    "scrollbar_thumb": _COLORS["scrollbar"],
    "scrollbar_thumb_hover": _COLORS["scrollbar.hover"],
    "sql_bg": _COLORS["code.bg"],
    "sql_text": _COLORS["data.mono"],
    "sql_keyword": _COLORS["code.keyword"],
    "sql_string": _COLORS["code.string"],
    "sql_number": _COLORS["code.number"],
    "sql_comment": _COLORS["code.comment"],
    "sql_function": _COLORS["accent.default"],
    "separator": _COLORS["border.subtle"],
    "btn_danger_bg": _COLORS["semantic.err.muted"],
    "btn_danger_hover": _COLORS["danger.btn.hover"],
    "btn_flat_hover": _COLORS["bg.hover"],
    "btn_cancel_bg": _COLORS["bg.pressed"],
    "vnc_bg": _COLORS["vnc.letterbox"],
    "table_header_bg": _COLORS["bg.sunken"],
    "table_header_text": _COLORS["text.secondary"],
    "warning_border": _COLORS["semantic.slow"],
    "warning_text": _COLORS["semantic.slow"],
    "warning_bg": _COLORS["semantic.slow.muted"],
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


_COLORS.update({
    "bg_primary": _COLORS["bg.app"],
    "bg_surface": _COLORS["bg.surface"],
    "bg_hover": _COLORS["bg.hover"],
    "bg_pressed": _COLORS["bg.pressed"],
    "text_primary": _COLORS["text.primary"],
    "text_secondary": _COLORS["text.secondary"],
    "text_tertiary": _COLORS["text.tertiary"],
    "text_link": _COLORS["text.link"],
    "text_on_accent": ("#FFFFFF", "#081522"),
})


def resolve(qss: str) -> str:
    """Подстановка @dot-токенов Signal Deck (longest-first)."""
    keys = sorted(_COLORS, key=len, reverse=True)
    for key in keys:
        qss = qss.replace("@" + key, color(key))
    return qss


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


