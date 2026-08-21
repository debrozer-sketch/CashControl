"""
help_css.py — CSS styles for HelpDialog HTML content.
"""

from __future__ import annotations

_CSS_LIGHT = """
<style>
  body {
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 13px;
    color: #1A1A2E;
    line-height: 1.6;
    margin: 0;
    padding: 0;
  }
  h1 {
    font-size: 20px;
    font-weight: 700;
    color: #1565C0;
    border-bottom: 2px solid #1565C0;
    padding-bottom: 6px;
    margin: 0 0 16px 0;
  }
  h2 {
    font-size: 15px;
    font-weight: 700;
    color: #1565C0;
    margin: 20px 0 8px 0;
    padding: 4px 0 4px 10px;
    border-left: 3px solid #42A5F5;
  }
  h3 {
    font-size: 13px;
    font-weight: 700;
    color: #333;
    margin: 14px 0 6px 0;
  }
  p  { margin: 4px 0 10px 0; }
  ul { margin: 4px 0 10px 18px; padding: 0; }
  li { margin-bottom: 4px; }
  code {
    background: #EEF2FF;
    color: #1565C0;
    border-radius: 3px;
    padding: 1px 5px;
    font-family: Consolas, monospace;
    font-size: 12px;
  }
  .note {
    background: #E3F2FD;
    border-left: 4px solid #1565C0;
    border-radius: 0 4px 4px 0;
    padding: 8px 12px;
    margin: 10px 0;
  }
  .warn {
    background: #FFF8E1;
    border-left: 4px solid #FFB300;
    border-radius: 0 4px 4px 0;
    padding: 8px 12px;
    margin: 10px 0;
  }
  .tip {
    background: #E8F5E9;
    border-left: 4px solid #2E7D32;
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
    background: #1565C0;
    color: white;
    padding: 6px 10px;
    text-align: left;
  }
  td {
    padding: 5px 10px;
    border-bottom: 1px solid #DDE1E8;
  }
  tr:nth-child(even) td { background: #F4F6F9; }
</style>
"""

_CSS_DARK = """
<style>
  body {
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 13px;
    color: #e0e0e0;
    line-height: 1.6;
    margin: 0;
    padding: 0;
    background-color: #1e1e1e;
  }
  h1 {
    font-size: 20px;
    font-weight: 700;
    color: #4fc3f7;
    border-bottom: 2px solid #4fc3f7;
    padding-bottom: 6px;
    margin: 0 0 16px 0;
  }
  h2 {
    font-size: 15px;
    font-weight: 700;
    color: #4fc3f7;
    margin: 20px 0 8px 0;
    padding: 4px 0 4px 10px;
    border-left: 3px solid #0288d1;
  }
  h3 { font-size: 13px; font-weight: 700; color: #bbbbbb; margin: 14px 0 6px 0; }
  p  { margin: 4px 0 10px 0; }
  ul { margin: 4px 0 10px 18px; padding: 0; }
  li { margin-bottom: 4px; }
  code {
    background: #2d2d2d;
    color: #4fc3f7;
    border-radius: 3px;
    padding: 1px 5px;
    font-family: Consolas, monospace;
    font-size: 12px;
  }
  .note {
    background: #1a2a3a;
    border-left: 4px solid #0288d1;
    border-radius: 0 4px 4px 0;
    padding: 8px 12px;
    margin: 10px 0;
  }
  .warn {
    background: #2a2a1a;
    border-left: 4px solid #FFB300;
    border-radius: 0 4px 4px 0;
    padding: 8px 12px;
    margin: 10px 0;
  }
  .tip {
    background: #1a2a1a;
    border-left: 4px solid #2E7D32;
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
    background: #0288d1;
    color: white;
    padding: 6px 10px;
    text-align: left;
  }
  td {
    padding: 5px 10px;
    border-bottom: 1px solid #333;
  }
  tr:nth-child(even) td { background: #2a2a2a; }
</style>
"""


def get_css() -> str:
    try:
        from qfluentwidgets import isDarkTheme
        return _CSS_DARK if isDarkTheme() else _CSS_LIGHT
    except Exception:
        return _CSS_LIGHT
