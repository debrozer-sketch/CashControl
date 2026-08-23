"""CashControl DB viewer: workers."""
from __future__ import annotations

import contextlib

import psycopg2
from PySide6.QtCore import QThread, Signal

from cashcontrol.gui.db_viewer.formatting import _human
from cashcontrol.gui.db_viewer.storage import _DbError


class _ConnFactory:  # Соединение psycopg2; пароли перебираются до первого успеха.

    def __init__(self, host, port, user, passwords, database):
        self.host, self.port, self.user = host, int(port), user
        self.passwords = list(passwords or [])
        self.database = database or 'postgres'

    def connect(self, database=None):
        db = database or self.database
        last = None
        for pw in self.passwords:
            try:
                return psycopg2.connect(host=self.host, port=self.port,
                                        user=self.user, password=pw, dbname=db,
                                        connect_timeout=5,
                                        application_name='CashControl',
                                        client_encoding='UTF8')
            except psycopg2.Error as e:
                last = e
        raise _DbError(f'Нет соединения с {self.user}@{self.host}:{self.port}/{db}: '
                       + (_human(last) if last else 'нет паролей'))


class _Worker(QThread):  # Выполняет fn(conn, worker) в отдельном потоке; отменяем при закрытии.
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, factory, fn, database=None, parent=None):
        super().__init__(parent)
        self._factory, self._fn, self._database = factory, fn, database

    def run(self):
        conn = None
        try:
            conn = self._factory.connect(self._database)
            res = self._fn(conn, self)
            if not self.isInterruptionRequested():
                self.done.emit(res)
        except Exception as e:
            if not self.isInterruptionRequested():
                self.failed.emit(_human(e))
        finally:
            if conn is not None:
                with contextlib.suppress(Exception):
                    conn.close()

    def cancel(self, wait_ms=1500):
        self.requestInterruption()
        self.wait(wait_ms)
        if self.isRunning():
            self.terminate()
            self.wait(500)


# # Каталог-запросы (портированы из pgweb/pkg/statements/sql/*.sql)

