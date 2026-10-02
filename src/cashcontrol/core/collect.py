"""Сбор диагностических данных с кассы в один архив.

Аналог функции «скачать логи» в SetConsole (ManageSet10). Там же цикл из
трёх шагов: упаковать на кассе через ``tar``, забрать архив по SCP, переименовать
локально добавив адрес и метку времени. Здесь то же самое, но без внешних
``plink``/``pscp``: команда уходит по уже открытому SSH-соединению сессии,
поэтому пароль нигде не появляется в списке процессов.

Набор путей и порядок совпадают с ``POS_save_logs.sh`` из ManageSet10:
    1. /home/tc/storage/crystal-cash/logs                       логи ПО кассы
    2. /home/tc/storage/comproxy/logs                          логи COM-порта
    3. .../modules/fiscalPrinter/templates                      шаблоны ФП
    4. /home/tc/storage/crystal-cash/config                    конфигурация
    5. /home/tc/storage/status.txt                             статус запуска

Пути заданы константой и переопределяются вызовом, если у конкретной кассы
состав каталогов отличается.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from cashcontrol.infrastructure.audit_logger import audit_log, get_logger

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

logger = get_logger()

#: Что упаковывается. Порядок совпадает с ManageSet10.
LOG_SOURCES: tuple[str, ...] = (
    "/home/tc/storage/crystal-cash/logs",
    "/home/tc/storage/comproxy/logs",
    "/home/tc/storage/crystal-cash/modules/fiscalPrinter/templates",
    "/home/tc/storage/crystal-cash/config",
    "/home/tc/storage/status.txt",
)

#: Куда на кассе складывается готовый архив до скачивания.
REMOTE_WORK_DIR = "/home/tc/storage"

#: Каталог для отчёта о размерах, измеряется до упаковки.
SIZE_REPORT_REMOTE = "/home/tc/storage/log_size.txt"

#: Архив логов, имя до локального переименования.
REMOTE_ARCHIVE = f"{REMOTE_WORK_DIR}/logs-cash.tar.gz"

#: Команда снятия скриншота экрана кассы.
SCREENSHOT_REMOTE_GLOB = "/home/tc/screenshot*.png"
_SCREENSHOT_CMD = (
    "rm -f /home/tc/screenshot*.png; "
    "/usr/local/bin/imlib2_grab /home/tc/screenshot_$(date +%m%d%H%M%S).png"
)

# Размер, после которого качать бессмысленно: архив не влезет в разумное время
# по SSH, а на кассе кончится место.
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024

_SIZE_LINE = re.compile(r"^(?P<size>[\d.]+[KMGT]?)\s+(?P<path>.+)$")


@dataclass
class Progress:
    """Ход сбора для интерфейса.

    ``percent`` считается по-разному на разных этапах: при упаковке по числу
    обработанных файлов из общего количества, при скачивании по байтам.
    На этапах, где точной величины нет, ``percent`` равен -1 и полоса
    показывается без процента.
    """

    stage: str
    percent: int
    detail: str
    elapsed: float = 0.0

    @property
    def stage_title(self) -> str:
        return STAGE_TITLES.get(self.stage, self.stage)


STAGE_TITLES = {
    "measure": "Измерение объёма",
    "count": "Подсчёт файлов",
    "pack": "Упаковка на кассе",
    "download": "Скачивание",
    "done": "Готово",
}


def count_files_command(sources: tuple[str, ...] = LOG_SOURCES) -> str:
    """Сколько всего записей попадёт в архив.

    Нужно для реального процента при упаковке: tar -v печатает по строке
    на каждый объект, включая каталоги, поэтому считаются все элементы
    без ограничения по типу. С ограничением ``-type f`` число занижалось
    и полоса доходила только до 99 процентов.
    """
    joined = " ".join(f'"{s}"' for s in sources)
    return f"find {joined} 2>/dev/null | wc -l"


@dataclass
class CollectResult:
    """Итог сбора с одной кассы."""

    ip: str
    archive: Path | None = None
    size_report: str = ""
    total_bytes: int = 0
    total_files: int = 0
    packed_files: int = 0
    warnings: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.archive is not None


def build_tar_command(
    sources: tuple[str, ...] = LOG_SOURCES,
    archive: str = REMOTE_ARCHIVE,
) -> str:
    """Команда упаковки, как в ManageSet10: tar -czvf с полными путями.

    Полные пути оставлены намеренно: в архиве сохраняется структура
    ``home/tc/storage/...``, и ``--transform`` не используется, потому что
    на TinyCore tar может быть busybox и эту опцию не понимает.
    """
    joined = " ".join(f'"{s}"' for s in sources)
    return f"rm -f {archive!r}; tar -czvf {archive!r} {joined}"


def build_size_command(
    sources: tuple[str, ...] = LOG_SOURCES,
    report: str = SIZE_REPORT_REMOTE,
) -> str:
    """du -hs по каталогам, результат пишется в файл отчёта.

    Меряется до упаковки: после ``tar -czf`` размер сжатого архива ничего
    не скажет о том, какая касса разрослась.
    """
    dirs = [s for s in sources if not s.endswith(".txt")]
    parts = [f"rm -f {report!r}", f": > {report!r}"]
    for d in dirs:
        parts.append(f'echo "== {d}" >> {report!r}')
        parts.append(f'du -hs "{d}" >> {report!r} 2>/dev/null')
    return "; ".join(parts)


def timestamp_label(when: datetime | None = None) -> str:
    """Метка для имени файла: ДД_ММ_ГГГГ-ЧЧ_ММ_СС, как в ManageSet10."""
    return (when or datetime.now()).strftime("%d_%m_%Y-%H_%M_%S")


def archive_name(ip: str, label: str | None = None) -> str:
    """Имя локального файла: logs-cash_<ip>_<метка>.tar.gz."""
    return f"logs-cash_{ip}_{label or timestamp_label()}.tar.gz"


async def _exec(session, command: str, timeout: float = 120.0) -> tuple[int, str, str]:
    result = await session.ssh.execute(command, timeout=timeout)
    return result.exit_code, result.stdout, result.stderr


#: Сообщения tar, которые не являются проблемой.
_TAR_NOISE = (
    "removing leading `/' from member names",
    "removing leading `/' from hard link targets",
)

#: Коды возврата tar: 0 — чисто, 1 — предупреждения, 2 и выше — ошибка.
TAR_OK = 0
TAR_WARNING = 1


def _tar_warnings(stderr: str) -> list[str]:
    """Существенные предупреждения tar без служебного шума.

    ``tar -czvf`` на работающей кассе почти всегда завершается кодом 1:
    активные логи растут во время упаковки, и GNU tar пишет
    ``file changed as we read it``. Архив при этом получается целым,
    поэтому код возврата нельзя трактовать как отказ.
    """
    out: list[str] = []
    for line in stderr.splitlines():
        text = line.strip()
        if not text.lower().startswith("tar:"):
            continue
        if any(n in text.lower() for n in _TAR_NOISE):
            continue
        if text not in out:
            out.append(text)
    return out


def _tar_reason(stderr: str) -> str:
    """Первая существенная строка из stderr tar для сообщения об ошибке."""
    lines = _tar_warnings(stderr)
    return lines[0] if lines else ""


async def collect_logs(
    session,
    dest_dir: Path,
    sources: tuple[str, ...] = LOG_SOURCES,
    *,
    keep_remote: bool = False,
    include_size_report: bool = True,
    on_progress: Callable[[Progress], None] | None = None,
) -> CollectResult:
    """Собрать логи кассы и скачать архив в ``dest_dir``.

    ``on_progress`` вызывается на каждом изменении хода работы: перед этапом,
    во время упаковки и во время скачивания. Вызывается из потока asyncio,
    интерфейс обязан передавать значение в GUI через сигнал.
    """
    ip = session.host
    result = CollectResult(ip=ip)
    dest_dir.mkdir(parents=True, exist_ok=True)
    label = timestamp_label()
    started = time.monotonic()

    def report(stage: str, percent: int, detail: str) -> None:
        if on_progress is not None:
            on_progress(
                Progress(
                    stage=stage,
                    percent=percent,
                    detail=detail,
                    elapsed=time.monotonic() - started,
                )
            )

    try:
        report("measure", -1, "Определение размера каталогов")
        if include_size_report:
            code, _out, _err = await _exec(session, build_size_command(sources), 60.0)
            if code != 0:
                logger.debug("Отчёт о размерах не собран на %s", ip)
            else:
                _c, out, _e = await _exec(session, f"cat {SIZE_REPORT_REMOTE!r}", 30.0)
                result.size_report = out.strip()

        report("count", -1, "Подсчёт файлов")
        _c, out, _e = await _exec(session, count_files_command(sources), 120.0)
        try:
            total_files = max(int(out.strip()), 0)
        except ValueError:
            total_files = 0

        packed = 0
        last_percent = -2

        def on_tar_line(_line: str) -> None:
            """tar -v печатает по строке на файл, это и есть ход упаковки."""
            nonlocal packed, last_percent
            packed += 1
            if total_files > 0:
                percent = min(int(packed * 100 / total_files), 99)
                if percent != last_percent:
                    last_percent = percent
                    report(
                        "pack",
                        percent,
                        f"{packed} из {total_files} файлов",
                    )
            elif packed % 25 == 0:
                report("pack", -1, f"Обработано файлов: {packed}")

        report("pack", -1, "Упаковка на кассе")
        tar_result = await session.ssh.execute_streaming(
            build_tar_command(sources), timeout=600, on_line=on_tar_line
        )
        tar_code = tar_result.exit_code
        err = tar_result.stderr
        result.total_files = total_files
        result.packed_files = packed
        result.warnings = _tar_warnings(err)

        _code, out, _err = await _exec(
            session, f"wc -c < {REMOTE_ARCHIVE!r}", 30.0
        )
        try:
            result.total_bytes = int(out.strip())
        except ValueError:
            result.total_bytes = 0

        if result.total_bytes <= 0:
            result.error = (
                "Не удалось упаковать на кассе: архив не создан. "
                f"{_tar_reason(err) or err.strip()[:200]}"
            )
            return result

        if tar_code >= 2:
            result.error = (
                f"Упаковка на кассе прервана с ошибкой ({tar_code}). "
                f"{_tar_reason(err) or err.strip()[:200]}"
            )
            return result

        if tar_code == TAR_WARNING and result.warnings:
            logger.info(
                "Архив с %s собран с предупреждениями: %s",
                ip,
                "; ".join(result.warnings[:3]),
            )

        if result.total_bytes > MAX_ARCHIVE_BYTES:
            result.error = (
                f"Архив {result.total_bytes // (1024 * 1024)} МБ больше "
                f"предела {MAX_ARCHIVE_BYTES // (1024 * 1024)} МБ"
            )
            return result

        target = dest_dir / archive_name(ip, label)
        ok = await _download(session, REMOTE_ARCHIVE, target, report, started)
        if not ok:
            result.error = "Не удалось скачать архив с кассы"
            return result

        result.archive = target
        report(
            "done",
            100,
            f"{target.name} — {human_size(target.stat().st_size)}",
        )
        if not keep_remote:
            await _exec(session, f"rm -f {REMOTE_ARCHIVE!r}", 30.0)

    except Exception as exc:
        result.error = str(exc)
        logger.error("Сбор логов с %s не удался: %s", ip, exc, exc_info=True)

    if result.ok:
        audit_log(
            action_type="tool",
            action_name="collect_logs",
            target=ip,
            result="success",
            details=f"{target.name}, {result.total_bytes} байт",
        )
    else:
        audit_log(
            action_type="tool",
            action_name="collect_logs",
            target=ip,
            result="failure",
            error_message=result.error or "",
        )
    return result


async def _download(
    session,
    remote: str,
    target: Path,
    report: Callable[[str, int, str], None] | None = None,
    started: float = 0.0,
) -> bool:
    """Скачать файл с отчётом о ходе по байтам."""
    state = {"last": -2}

    def on_progress(_src, _dst, offset: int, total: int) -> None:
        if report is None:
            return
        percent = int(offset * 100 / total) if total else -1
        if percent == state["last"]:
            return
        state["last"] = percent
        speed = ""
        if started and offset > 0:
            spent = time.monotonic() - started
            if spent > 0.5:
                speed = f", {human_size(offset / spent)}/с"
        report(
            "download",
            min(percent, 99),
            f"{human_size(offset)} из {human_size(total)}{speed}",
        )

    try:
        await session.ssh.download_file(remote, str(target), progress_handler=on_progress)
        return target.is_file() and target.stat().st_size > 0
    except Exception as exc:
        logger.error("Скачивание %s не удалось: %s", remote, exc, exc_info=True)
        target.unlink(missing_ok=True)
        return False


async def take_screenshot(session, timeout: float = 60.0) -> str:
    """Снять скриншот экрана кассы. Возвращает путь на самой кассе."""
    try:
        code, _out, _err = await _exec(session, _SCREENSHOT_CMD, timeout)
        if code != 0:
            return ""
        _c, out, _e = await _exec(
            session, f"ls -1 {SCREENSHOT_REMOTE_GLOB!r} 2>/dev/null | tail -1", 20.0
        )
        return out.strip().splitlines()[-1] if out.strip() else ""
    except Exception as exc:
        logger.error("Скриншот %s не удался: %s", session.host, exc)
        return ""


def parse_size_report(text: str) -> dict[str, str]:
    """Разобрать вывод ``du -hs`` в словарь путь → размер."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        m = _SIZE_LINE.match(line.strip())
        if m:
            out[m.group("path").strip()] = m.group("size")
    return out


_UNITS = {"Б": 1, "K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}


def _to_bytes(size_text: str) -> int:
    """'12M' → байты. du -hs печатает K/M/G без пробела."""
    m = re.match(r"^([\d.]+)\s*([KMGT]?)$", size_text.strip(), re.IGNORECASE)
    if not m:
        return 0
    value, unit = m.group(1), m.group(2).upper()
    return int(float(value) * _UNITS.get(unit, 1))


def largest_source(text: str) -> tuple[str, str] | None:
    """Самый объёмный каталог из отчёта du: (размер, путь).

    Показывается в уведомлении, чтобы сразу было видно, что именно
    разрослось, не открывая архив.
    """
    sizes = parse_size_report(text)
    if not sizes:
        return None
    path, size = max(sizes.items(), key=lambda kv: _to_bytes(kv[1]))
    return size, path


def human_size(num: int) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if num < 1024 or unit == "ГБ":
            return f"{num:.0f} {unit}" if unit == "Б" else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} ГБ"


def default_dest_dir() -> Path:
    """Каталог для архивов рядом с программой."""
    from cashcontrol.infrastructure.path_resolver import get_data_dir

    return get_data_dir() / "collected"


__all__ = [
    "LOG_SOURCES",
    "CollectResult",
    "archive_name",
    "build_size_command",
    "build_tar_command",
    "collect_logs",
    "default_dest_dir",
    "human_size",
    "largest_source",
    "parse_size_report",
    "take_screenshot",
    "timestamp_label",
]
