"""CashControl DB viewer: sql."""
from __future__ import annotations

import csv
import json
import re
from datetime import date, datetime
from datetime import time as dtime
from decimal import Decimal

from psycopg2 import sql as pgsql

from cashcontrol.builtin.db_viewer.formatting import _fmt, _qtable
from cashcontrol.builtin.db_viewer.storage import _DbError

_LIKE_ESCAPE_RE = re.compile(r'([\\%_])')

_SQL_DATABASES = "SELECT datname FROM pg_database WHERE NOT datistemplate ORDER BY 1"
_SQL_TABLES = """SELECT c.relname AS name, c.relkind AS kind, c.reltuples::bigint AS est
    FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname=%s AND c.relkind IN ('r','p','v','m') ORDER BY c.relname"""
_SQL_COLUMNS = """SELECT a.attname AS name, format_type(a.atttypid,a.atttypmod) AS type,
    NOT a.attnotnull AS nullable, COALESCE(pg_get_expr(ad.adbin,ad.adrelid),'') AS default_value,
    COALESCE(col_description(a.attrelid,a.attnum),'') AS comment
    FROM pg_attribute a LEFT JOIN pg_attrdef ad ON a.attrelid=ad.adrelid AND a.attnum=ad.adnum
    WHERE a.attrelid=%s::regclass AND a.attnum>0 AND NOT a.attisdropped ORDER BY a.attnum"""
_SQL_PK = """SELECT a.attname FROM pg_index i
    JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=ANY(i.indkey)
    WHERE i.indrelid=%s::regclass AND i.indisprimary
    ORDER BY array_position(i.indkey,a.attnum)"""
_SQL_ESTIMATED = """SELECT reltuples::bigint FROM pg_class c
    JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND c.relname=%s"""
_SQL_COMPLETION = """SELECT n.nspname,c.relname,a.attname FROM pg_class c
    JOIN pg_namespace n ON n.oid=c.relnamespace
    JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
    WHERE n.nspname NOT IN ('pg_catalog','information_schema')
      AND c.relkind IN ('r','p','v','m') ORDER BY 1,2,a.attnum"""


def _load_meta(conn, worker, schema, table):
    if worker is not None and worker.isInterruptionRequested():
        raise _DbError('отменено')
    qname = _qtable(schema, table)
    cur = conn.cursor()
    cur.execute(_SQL_COLUMNS, (qname,))
    columns = [dict(zip(('name', 'type', 'nullable', 'default', 'comment'), r, strict=False))
               for r in cur.fetchall()]
    cur.execute(_SQL_PK, (qname,))
    pk = [r[0] for r in cur.fetchall()]
    cur.execute(_SQL_ESTIMATED, (schema, table))
    estimated = cur.fetchone()[0] or 0
    return {'columns': columns, 'pk': pk, 'estimated': max(0, int(estimated))}


# # Серверный фильтр (pgweb-style): whitelisted операторы, pgsql.Literal

_IDENT_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_$]*')


def _split(text):
    parts, cur, in_q = [], '', False
    for ch in text:
        if ch == "'":
            in_q = not in_q
            cur += ch
        elif ch == ',' and not in_q:
            parts.append(cur)
            cur = ''
        else:
            cur += ch
    if cur.strip():
        parts.append(cur)
    return parts


def _parse_literal(raw):
    s = raw.strip()
    if not s:
        raise ValueError('пустое значение')
    if s.startswith("'") and s.endswith("'"):
        return s[1:-1].replace("''", "'")
    if s.upper() == 'NULL':
        return None
    if s.upper() == 'TRUE':
        return True
    if s.upper() == 'FALSE':
        return False
    if re.fullmatch(r'-?\d+', s):
        return int(s)
    if re.fullmatch(r'-?\d+\.\d+([eE][+-]?\d+)?', s):
        return float(s)
    return s


def _build_where(filter_text, columns):
    """'id > 10, name LIKE \'A%\'' → AND-цепочка pgsql-условий.

    Операторы: = != > < >= <= LIKE ILIKE IN IS NULL. Колонки — только из
    каталога (квотируются), значения — pgsql.Literal (экранирование).
    """
    names = {c['name'] for c in columns}
    parts = []
    for raw in _split(filter_text):
        s = raw.strip()
        if not s:
            continue
        m = _IDENT_RE.match(s)
        if not m:
            raise ValueError(f'Некорректный фильтр: «{raw}»')
        col = m.group(0)
        if col not in names:
            raise ValueError(f'Колонка «{col}» не найдена в таблице')
        rest = s[m.end():].strip()
        if rest.upper() == 'IS NULL':
            parts.append(pgsql.SQL('{} IS NULL').format(pgsql.Identifier(col)))
            continue
        opm = re.match(r'^(<=|>=|!=|<>|=|>|<|LIKE|ILIKE|IN)(.*)$', rest,
                       re.I | re.S)
        if not opm:
            raise ValueError(f'Неизвестный оператор в «{raw}» (разрешены: '
                             '= != > < >= <= LIKE ILIKE IN IS NULL)')
        op, val = opm.group(1).upper(), opm.group(2).strip()
        ident = pgsql.Identifier(col)
        if op == 'IN':
            if not (val.startswith('(') and val.endswith(')')):
                raise ValueError(f'IN требует список в скобках: «{raw}»')
            items = [_parse_literal(x) for x in _split(val[1:-1])]
            if not items:
                raise ValueError(f'Пустой список IN: «{raw}»')
            parts.append(pgsql.SQL('{} IN ({})').format(
                ident, pgsql.SQL(', ').join(pgsql.Literal(v) for v in items)))
        elif op in ('LIKE', 'ILIKE'):
            parts.append(pgsql.SQL('{} {} {}').format(
                ident, pgsql.SQL(op), pgsql.Literal(_parse_literal(val))))
        else:
            parts.append(pgsql.SQL('{} {} {}').format(
                ident, pgsql.SQL('!=' if op == '<>' else op),
                pgsql.Literal(_parse_literal(val))))
    if not parts:
        raise ValueError('пустой фильтр')
    return pgsql.SQL(' AND ').join(parts)


def _search_where(text, columns, only_col=None):
    """Подстрочный поиск по всей таблице.

    Возвращает условие вида ``col1::text ILIKE '%q%' OR col2::text …`` либо
    ``None``, если искать нечем.

    Три решения, каждое — по необходимости:

    - приведение ``::text`` обязательно: в кассовых таблицах встречаются
      jsonb и массивы, а оператора ``ILIKE`` у них нет, и запрос упал бы с
      «operator does not exist» на первой же такой колонке;
    - ``%`` и ``_`` экранируются: поиск строки «50%» обязан искать текст
      «50%», а не работать как шаблон;
    - условие всегда в скобках, потому что вызывающая сторона склеивает его
      с фильтром через ``AND``.
    """
    text = (text or '').strip()
    if not text:
        return None
    names = [only_col] if only_col else [c['name'] for c in columns]
    if not names:
        return None
    pattern = '%' + _LIKE_ESCAPE_RE.sub(r'\\\1', text) + '%'
    literal = pgsql.Literal(pattern)
    parts = [
        pgsql.SQL('{}::text ILIKE {} ESCAPE {}').format(
            pgsql.Identifier(name), literal, pgsql.Literal('\\'))
        for name in names
    ]
    return pgsql.SQL('({})').format(pgsql.SQL(' OR ').join(parts))


def _sel_query(schema, table, columns, where, order, limit=None, offset=None):
    cols = pgsql.SQL(', ').join(pgsql.Identifier(c['name']) for c in columns)
    q = pgsql.SQL('SELECT {cols} FROM {t}').format(
        cols=cols, t=pgsql.SQL('{}.{}').format(pgsql.Identifier(schema),
                                               pgsql.Identifier(table)))
    if where is not None:
        q = q + pgsql.SQL(' WHERE ') + where
    if order is not None:
        q = q + pgsql.SQL(' ORDER BY {} {}').format(
            pgsql.Identifier(order[0]), pgsql.SQL(order[1]))
    if limit is not None:
        # LIMIT и OFFSET уходят литералами, а не плейсхолдерами %s.
        # psycopg2 при передаче params прогоняет собранный текст через
        # %-подстановку, и любой «%» из данных пользователя становился бы
        # спецсимволом формата: поиск «DNS1» давал «%DNS1%» и запрос падал
        # с «tuple index out of range». С литералами подстановки нет вовсе,
        # и данные оператора не могут быть прочитаны как формат.
        q = q + pgsql.SQL(' LIMIT {} OFFSET {}').format(
            pgsql.Literal(limit), pgsql.Literal(offset))
    return q


def _load_page(conn, worker, schema, table, limit, offset, order, filter_text,
               search_text='', search_col=None):
    meta = _load_meta(conn, worker, schema, table)
    # Условие поиска и условие фильтра склеиваются, а не заменяют друг
    # друга: «ищу DNS1» и «только строки с id > 10» — два независимых
    # ограничения одного запроса.
    clauses = []
    if filter_text.strip():
        clauses.append(_build_where(filter_text, meta['columns']))
    search = _search_where(
        search_text.strip(), meta['columns'], search_col)
    if search is not None:
        clauses.append(search)
    where = pgsql.SQL(' AND ').join(clauses) if clauses else None
    cur = conn.cursor()
    # params не передаются: все значения, включая LIMIT/OFFSET, уходят
    # литералами. См. комментарий в _sel_query про %-подстановку psycopg2.
    cur.execute(_sel_query(schema, table, meta['columns'], where, order,
                           limit, offset))
    rows = []
    while True:
        batch = cur.fetchmany(200)
        if not batch:
            break
        rows.extend(batch)
        if worker is not None and worker.isInterruptionRequested():
            raise _DbError('отменено')
    if where is not None:
        cur.execute(pgsql.SQL('SELECT count(*) FROM {t}').format(
            t=pgsql.SQL('{}.{}').format(pgsql.Identifier(schema),
                                        pgsql.Identifier(table)))
            + pgsql.SQL(' WHERE ') + where)
        count = int(cur.fetchone()[0])
    else:
        count = meta['estimated']
    return {'meta': meta, 'rows': rows, 'count': count}


# # Экспорт / импорт

def _csv_cell(v):
    if v is None:
        return ''
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, (datetime, date, dtime, bytes, bytearray, memoryview)):
        return _fmt(v)
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def _json_value(v):
    if isinstance(v, Decimal):
        try:
            return float(v)
        except Exception:
            return str(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        return '\\x' + bytes(v).hex()
    if isinstance(v, (datetime, date, dtime)):
        return _fmt(v)
    return v


def _export_rows(conn, worker, schema, table, columns, where, order, path, fmt):
    cur = conn.cursor()
    cur.execute(_sel_query(schema, table, columns, where, order))
    n = 0
    if fmt == 'csv':
        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f, delimiter=';')
            w.writerow([c['name'] for c in columns])
            while True:
                batch = cur.fetchmany(1000)
                if not batch:
                    break
                for r in batch:
                    w.writerow([_csv_cell(v) for v in r])
                n += len(batch)
                if worker is not None and worker.isInterruptionRequested():
                    raise _DbError('отменено')
    else:
        names = [c['name'] for c in columns]
        with open(path, 'w', encoding='utf-8') as f:
            f.write('[')
            first = True
            while True:
                batch = cur.fetchmany(1000)
                if not batch:
                    break
                for r in batch:
                    f.write(('' if first else ',\n') + json.dumps(
                        {nm: _json_value(v) for nm, v in zip(names, r, strict=False)},
                        ensure_ascii=False))
                    first = False
                n += len(batch)
                if worker is not None and worker.isInterruptionRequested():
                    raise _DbError('отменено')
            f.write(']')
    return n


# # Грид данных

