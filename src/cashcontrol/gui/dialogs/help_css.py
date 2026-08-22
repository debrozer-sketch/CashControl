"""
help_css.py — CSS/QSS styles for HelpDialog.

Single source of truth: one template per surface + a palette per theme.
Palettes are resolved 1-1 from theme_helper tokens.
"""

from __future__ import annotations

from string import Template

from cashcontrol.gui.theme_helper import color as _tc

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

def _theme_name() -> str:
    try:
        from qfluentwidgets import isDarkTheme

        return "dark" if isDarkTheme() else "light"
    except Exception:
        return "light"


def _palette() -> dict[str, str]:
    dark = _theme_name() == "dark"
    return {
        "text": _tc("text_primary"),
        "body_bg": _tc("bg_code") if dark else "transparent",
        "accent": _tc("text_link") if dark else _tc("accent"),
        "h2_border": _tc("info"),
        "h3_color": _tc("text_secondary") if dark else _tc("text_primary"),
        "code_bg": _tc("bg_secondary") if dark else _tc("bg_code"),
        "note_bg": _tc("bg_info"),      "note_border": _tc("info"),
        "warn_bg": _tc("bg_warning"),   "warn_border": _tc("warning_border"),
        "tip_bg": _tc("bg_success"),    "tip_border": _tc("success"),
        "th_bg": _tc("text_link") if dark else _tc("accent"),
        "td_border": _tc("border_secondary"),
        "row_even": _tc("bg_table_alt"),
    }


def _tree_palette() -> dict[str, str]:
    return {"panel_bg": _tc("bg_secondary"), "text": _tc("text_primary"),
            "sel_bg": _tc("accent"), "hover_bg": _tc("bg_hover")}


def get_css() -> str:
    """Full page CSS for the current theme."""
    return _PAGE_CSS.substitute(_palette())


def get_tree_stylesheet() -> str:
    """QSS for the sections tree on the current theme."""
    return _TREE_QSS.substitute(_tree_palette())


def get_panel_bg() -> str:
    """Panel background color for the current theme."""
    return _tree_palette()["panel_bg"]


def get_scroll_bg() -> str:
    """Scroll area background for the current theme."""
    return _tc("bg_code") if _theme_name() == "dark" else _tc("bg_primary")
