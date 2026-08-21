"""
help_css.py — CSS/QSS styles for HelpDialog.

Single source of truth: one template per surface + a palette per theme.
"""

from __future__ import annotations

from string import Template

# ── Palettes ──────────────────────────────────────────────────────────────

_PALETTES: dict[str, dict[str, str]] = {
    "light": {
        "text": "#1A1A2E",
        "body_bg": "transparent",
        "accent": "#1565C0",
        "h2_border": "#42A5F5",
        "h3_color": "#333333",
        "code_bg": "#EEF2FF",
        "note_bg": "#E3F2FD",
        "note_border": "#1565C0",
        "warn_bg": "#FFF8E1",
        "warn_border": "#FFB300",
        "tip_bg": "#E8F5E9",
        "tip_border": "#2E7D32",
        "th_bg": "#1565C0",
        "td_border": "#DDE1E8",
        "row_even": "#F4F6F9",
    },
    "dark": {
        "text": "#e0e0e0",
        "body_bg": "#1e1e1e",
        "accent": "#4fc3f7",
        "h2_border": "#0288d1",
        "h3_color": "#bbbbbb",
        "code_bg": "#2d2d2d",
        "note_bg": "#1a2a3a",
        "note_border": "#0288d1",
        "warn_bg": "#2a2a1a",
        "warn_border": "#FFB300",
        "tip_bg": "#1a2a1a",
        "tip_border": "#2E7D32",
        "th_bg": "#0288d1",
        "td_border": "#333333",
        "row_even": "#2a2a2a",
    },
}

# ── HTML page CSS ─────────────────────────────────────────────────────────

_PAGE_CSS = Template(
    """
<style>
  body {
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 13px;
    color: $text;
    line-height: 1.6;
    margin: 0;
    padding: 0;
    background-color: $body_bg;
  }
  h1 {
    font-size: 20px;
    font-weight: 700;
    color: $accent;
    border-bottom: 2px solid $accent;
    padding-bottom: 6px;
    margin: 0 0 16px 0;
  }
  h2 {
    font-size: 15px;
    font-weight: 700;
    color: $accent;
    margin: 20px 0 8px 0;
    padding: 4px 0 4px 10px;
    border-left: 3px solid $h2_border;
  }
  h3 { font-size: 13px; font-weight: 700; color: $h3_color; margin: 14px 0 6px 0; }
  p  { margin: 4px 0 10px 0; }
  ul { margin: 4px 0 10px 18px; padding: 0; }
  li { margin-bottom: 4px; }
  code {
    background: $code_bg;
    color: $accent;
    border-radius: 3px;
    padding: 1px 5px;
    font-family: Consolas, monospace;
    font-size: 12px;
  }
  .note {
    background: $note_bg;
    border-left: 4px solid $note_border;
    border-radius: 0 4px 4px 0;
    padding: 8px 12px;
    margin: 10px 0;
  }
  .warn {
    background: $warn_bg;
    border-left: 4px solid $warn_border;
    border-radius: 0 4px 4px 0;
    padding: 8px 12px;
    margin: 10px 0;
  }
  .tip {
    background: $tip_bg;
    border-left: 4px solid $tip_border;
    border-radius: 0 4px 4px 0;
    padding: 8px 12px;
    margin: 10px 0;
  }
  table {
    border-collapse: collapse;
    width: 100%;
    margin: 8px 0 14px 0;
    font-size: 12px;
  }
  th {
    background: $th_bg;
    color: white;
    padding: 6px 10px;
    text-align: left;
  }
  td {
    padding: 5px 10px;
    border-bottom: 1px solid $td_border;
  }
  tr:nth-child(even) td { background: $row_even; }
</style>
"""
)

# ── Tree widget QSS ───────────────────────────────────────────────────────

_TREE_QSS = Template(
    """
    QTreeWidget {
        background: $panel_bg;
        color: $text;
        border: none;
        font-size: 13px;
        outline: none;
    }
    QTreeWidget::item {
        padding: 5px 8px;
        border-radius: 4px;
    }
    QTreeWidget::item:selected {
        background: $sel_bg;
        color: white;
    }
    QTreeWidget::item:hover:!selected {
        background: $hover_bg;
    }
"""
)

_TREE_PALETTES: dict[str, dict[str, str]] = {
    "light": {
        "panel_bg": "#F0F4FA",
        "text": "#1A1A2E",
        "sel_bg": "#1565C0",
        "hover_bg": "#D8E4F5",
    },
    "dark": {
        "panel_bg": "#1e2a3a",
        "text": "#e0e0e0",
        "sel_bg": "#0277bd",
        "hover_bg": "#1a3a5a",
    },
}


def _theme_name() -> str:
    try:
        from qfluentwidgets import isDarkTheme

        return "dark" if isDarkTheme() else "light"
    except Exception:
        return "light"


def get_css() -> str:
    """Full page CSS for the current theme."""
    return _PAGE_CSS.substitute(_PALETTES[_theme_name()])


def get_tree_stylesheet() -> str:
    """QSS for the sections tree on the current theme."""
    return _TREE_QSS.substitute(_TREE_PALETTES[_theme_name()])


def get_panel_bg() -> str:
    """Panel background color for the current theme."""
    return _TREE_PALETTES[_theme_name()]["panel_bg"]


def get_scroll_bg() -> str:
    """Scroll area background for the current theme."""
    return _PALETTES[_theme_name()]["body_bg"] if _theme_name() == "dark" else "white"
