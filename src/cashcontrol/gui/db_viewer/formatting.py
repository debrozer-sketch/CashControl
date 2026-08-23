"""CashControl DB viewer: formatting."""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from datetime import time as dtime
from decimal import Decimal, InvalidOperation

from PySide6.QtGui import (
    QFontDatabase,
)

try:
    from cashcontrol.gui.theme_helper import color as _tc
except Exception:
    def _tc(name):
        raise KeyError(name)


def _c(name, fallback='#616161'):
    try:
        return _tc(name)
    except Exception:
        return fallback


def _qi(n):
    return '"' + str(n).replace('"', '""') + '"'


def _qtable(s, t):
    return f'{_qi(s)}.{_qi(t)}'


def _mono():
    f = QFontDatabase.systemFont(QFontDatabase.FixedFont)
    f.setPointSize(QFontDatabase.systemFont(QFontDatabase.GeneralFont).pointSize())
    return f


def _fmt(v):
    if v is None:
        return 'NULL'
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, datetime):
        try:
            return v.astimezone().strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            return v.strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(v, dtime):
        return v.strftime('%H:%M:%S')
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray, memoryview)):
        return '\\x' + bytes(v).hex()
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def _kind(t):
    t = t.lower()
    if t.endswith('[]'):
        return 'other'
    if t.startswith(('smallint', 'integer', 'bigint', 'int2', 'int4', 'int8',
                     'oid', 'serial', 'bigserial', 'smallserial')):
        return 'int'
    if t.startswith(('numeric', 'decimal', 'money')):
        return 'num'
    if t.startswith(('real', 'double precision', 'float4', 'float8')):
        return 'float'
    if t.startswith('bool'):
        return 'bool'
    if t.startswith(('date', 'time', 'timestamp')):
        return 'time'
    if t.startswith('json'):
        return 'json'
    return 'text'


_EDITABLE = ('int', 'num', 'float', 'bool', 'time', 'json', 'text')


def _parse_value(text, coltype):
    s = text.strip()
    if not s or s.upper() == 'NULL':
        return None
    k = _kind(coltype)
    try:
        if k == 'int':
            return int(s)
        if k == 'num':
            return Decimal(s)
        if k == 'float':
            return float(s)
        if k == 'bool':
            low = s.lower()
            if low in ('true', 't', '1', 'yes', 'да'):
                return True
            if low in ('false', 'f', '0', 'no', 'нет'):
                return False
            raise ValueError(f'ожидалось true/false, а не «{text}»')
        if k == 'time':
            return datetime.fromisoformat(s.replace('Z', '+00:00'))
        if k == 'json':
            return json.loads(s)
    except (ValueError, InvalidOperation) as e:
        raise ValueError(f'«{text}» не разобрать как {coltype}: {e}')
    return text


def _human(e):
    diag = getattr(e, 'diag', None)
    msg = (diag.message_primary or diag.message_detail) if diag else ''
    s = (msg or str(e)).strip()
    s = re.sub(r'\s+', ' ', s)
    return s[:300] + '…' if len(s) > 300 else (s or e.__class__.__name__)


