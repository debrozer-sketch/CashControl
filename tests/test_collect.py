"""Тесты сбора логов и данных кассы (аналог функции SetConsole).

Состав путей и формат имени архива должны совпадать с оригиналом из
``C:\\ManageSet10\\POS_save_logs.sh``, иначе поддержка не сможет читать
собранные старой программой файлы.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from cashcontrol.core.collect import (
    LOG_SOURCES,
    MAX_ARCHIVE_BYTES,
    REMOTE_ARCHIVE,
    archive_name,
    build_size_command,
    build_tar_command,
    collect_logs,
    count_files_command,
    human_size,
    largest_source,
    parse_size_report,
    take_screenshot,
    timestamp_label,
)


class _FakeSSH:
    """Заглушка SSH: отвечает заранее заданными результатами."""

    def __init__(self, responses: dict[str, tuple[int, str, str]]):
        self._responses = responses
        self.commands: list[str] = []
        self.downloaded: list[tuple[str, str]] = []

    def _reply(self, command: str):
        for needle, value in self._responses.items():
            if needle in command:
                return SimpleNamespace(exit_code=value[0], stdout=value[1], stderr=value[2])
        return SimpleNamespace(exit_code=0, stdout="", stderr="")

    async def execute(self, command: str, timeout: int | None = None, check: bool = False):
        self.commands.append(command)
        return self._reply(command)

    async def execute_streaming(
        self, command: str, timeout: int | None = None, on_line=None
    ):
        self.commands.append(command)
        reply = self._reply(command)
        if on_line is not None:
            for line in reply.stdout.splitlines():
                on_line(line + "\n")
        return reply

    async def download_file(
        self, remote_path: str, local_path: str, preserve: bool = True, progress_handler=None
    ):
        self.downloaded.append((remote_path, local_path))
        Path(local_path).write_bytes(b"fake-archive" * 512)
        if progress_handler is not None:
            total = Path(local_path).stat().st_size
            progress_handler(remote_path, local_path, total // 2, total)
            progress_handler(remote_path, local_path, total, total)


def _session(ssh: _FakeSSH):
    return SimpleNamespace(host="10.0.0.7", ssh=ssh, is_connected=True)


# ── Соответствие оригиналу ───────────────────────────────────────────


def test_log_sources_match_setconsole():
    assert LOG_SOURCES == (
        "/home/tc/storage/crystal-cash/logs",
        "/home/tc/storage/comproxy/logs",
        "/home/tc/storage/crystal-cash/modules/fiscalPrinter/templates",
        "/home/tc/storage/crystal-cash/config",
        "/home/tc/storage/status.txt",
    )


def test_tar_command_has_all_five_sources():
    cmd = build_tar_command()
    assert cmd.startswith(f"rm -f '{REMOTE_ARCHIVE}'")
    assert "tar -czvf" in cmd
    for src in LOG_SOURCES:
        assert f'"{src}"' in cmd


def test_tar_command_avoids_transform_for_busybox():
    """На TinyCore tar может быть busybox и не понимать --transform."""
    assert "--transform" not in build_tar_command()


def test_size_command_uses_du_and_skips_status_txt():
    cmd = build_size_command()
    assert "du -hs" in cmd
    for d in LOG_SOURCES[:4]:
        assert f'du -hs "{d}"' in cmd
    # status.txt — файл, его размер бессмысленно мерить через du
    assert 'du -hs "/home/tc/storage/status.txt"' not in cmd


def test_archive_name_matches_setconsole_format():
    label = timestamp_label(datetime(2026, 9, 29, 14, 5, 7))
    assert label == "29_09_2026-14_05_07"
    assert archive_name("10.0.0.7", label) == "logs-cash_10.0.0.7_29_09_2026-14_05_07.tar.gz"


# ── Разбор отчёта о размерах ────────────────────────────────────────

_REPORT = """== /home/tc/storage/crystal-cash/logs
1.2G	/home/tc/storage/crystal-cash/logs
250M	/home/tc/storage/comproxy/logs
12K	/home/tc/storage/crystal-cash/config"""


def test_parse_size_report():
    sizes = parse_size_report(_REPORT)
    assert sizes["/home/tc/storage/crystal-cash/logs"] == "1.2G"
    assert len(sizes) == 3


def test_largest_source_picks_biggest():
    assert largest_source(_REPORT) == ("1.2G", "/home/tc/storage/crystal-cash/logs")


def test_largest_source_on_empty_report():
    assert largest_source("") is None
    assert largest_source("мусор без чисел") is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1.2G", 1288490188), ("250M", 262144000), ("12K", 12288), ("0", 0)],
)
def test_size_units_converted(value, expected):
    from cashcontrol.core.collect import _to_bytes

    assert abs(_to_bytes(value) - expected) <= 2


def test_human_size():
    assert human_size(512) == "512 Б"
    assert human_size(1536) == "1.5 КБ"
    assert human_size(5 * 1024 * 1024) == "5.0 МБ"


# ── Сбор архива ──────────────────────────────────────────────────────


def test_collect_downloads_and_renames(tmp_path):
    ssh = _FakeSSH({"wc -c": (0, "2048", "")})
    result = asyncio.run(collect_logs(_session(ssh), tmp_path))

    assert result.ok, result.error
    assert result.total_bytes == 2048
    assert result.archive is not None
    assert result.archive.parent == tmp_path
    assert result.archive.name.startswith("logs-cash_10.0.0.7_")
    assert result.archive.name.endswith(".tar.gz")
    assert ssh.downloaded == [(REMOTE_ARCHIVE, str(result.archive))]


def test_collect_archives_before_downloading(tmp_path):
    """Порядок как в SetConsole: сначала tar, потом скачивание."""
    ssh = _FakeSSH({"wc -c": (0, "10", "")})
    asyncio.run(collect_logs(_session(ssh), tmp_path))

    tar_index = next(i for i, c in enumerate(ssh.commands) if "tar -czvf" in c)
    du_index = next(i for i, c in enumerate(ssh.commands) if "du -hs" in c)
    assert du_index < tar_index
    assert ssh.downloaded


def test_collect_removes_remote_archive_by_default(tmp_path):
    ssh = _FakeSSH({"wc -c": (0, "10", "")})
    asyncio.run(collect_logs(_session(ssh), tmp_path))
    assert any(c.endswith(f"rm -f '{REMOTE_ARCHIVE}'") for c in ssh.commands)


def test_collect_keeps_remote_archive_when_asked(tmp_path):
    ssh = _FakeSSH({"wc -c": (0, "10", "")})
    asyncio.run(collect_logs(_session(ssh), tmp_path, keep_remote=True))
    assert not any(c.endswith(f"rm -f '{REMOTE_ARCHIVE}'") for c in ssh.commands)


def test_collect_reads_size_report(tmp_path):
    # du-команда тоже содержит log_size.txt, поэтому матчим именно чтение файла
    ssh = _FakeSSH({"cat ": (0, _REPORT, "")})
    result = asyncio.run(collect_logs(_session(ssh), tmp_path))
    assert result.size_report == _REPORT.strip()


def test_collect_reports_tar_failure(tmp_path):
    """Код 2 и выше — настоящая ошибка, даже если остался частичный архив."""
    ssh = _FakeSSH(
        {
            "tar -czvf": (2, "", "Cannot stat: No such file or directory"),
            "wc -c": (0, "512", ""),
        }
    )
    result = asyncio.run(collect_logs(_session(ssh), tmp_path))

    assert not result.ok
    assert "прервана с ошибкой" in result.error
    assert "Cannot stat" in result.error
    assert ssh.downloaded == []


def test_collect_accepts_tar_warning_exit_1(tmp_path):
    """GNU tar отдаёт 1 на живых логах, архив при этом целый."""
    ssh = _FakeSSH(
        {
            "tar -czvf": (
                1,
                "",
                "tar: Removing leading `/' from member names\n"
                "tar: /home/tc/storage/crystal-cash/logs/app.log: file changed as we read it",
            ),
            "wc -c": (0, "4096", ""),
        }
    )
    result = asyncio.run(collect_logs(_session(ssh), tmp_path))

    assert result.ok, result.error
    assert result.total_bytes == 4096
    assert len(ssh.downloaded) == 1
    assert any("file changed as we read it" in w for w in result.warnings)


def test_collect_ignores_leading_slash_noise(tmp_path):
    """Это сообщение GNU tar о пути, а не проблема."""
    ssh = _FakeSSH(
        {
            "tar -czvf": (
                0,
                "",
                "tar: Removing leading `/' from member names\n"
                "tar: Removing leading `/' from hard link targets",
            ),
            "wc -c": (0, "4096", ""),
        }
    )
    result = asyncio.run(collect_logs(_session(ssh), tmp_path))

    assert result.ok
    assert result.warnings == []


def test_collect_fails_when_archive_not_created(tmp_path):
    """Код 0, но архива нет — значит упаковка не удалась."""
    ssh = _FakeSSH(
        {
            "tar -czvf": (0, "", "tar: Cannot stat: No such file or directory"),
            "wc -c": (0, "0", ""),
        }
    )
    result = asyncio.run(collect_logs(_session(ssh), tmp_path))

    assert not result.ok
    assert "архив не создан" in result.error
    assert "Cannot stat" in result.error
    assert ssh.downloaded == []


def test_collect_rejects_oversized_archive(tmp_path):
    ssh = _FakeSSH({"wc -c": (0, str(MAX_ARCHIVE_BYTES + 1), "")})
    result = asyncio.run(collect_logs(_session(ssh), tmp_path))

    assert not result.ok
    assert "предела" in result.error
    assert ssh.downloaded == []


def test_collect_survives_session_error(tmp_path):
    class _Boom:
        async def execute(self, *_a, **_kw):
            raise OSError("соединение потеряно")

        async def download_file(self, *_a, **_kw):
            raise OSError("соединение потеряно")

    session = SimpleNamespace(host="10.0.0.7", ssh=_Boom(), is_connected=True)
    result = asyncio.run(collect_logs(session, tmp_path))

    assert not result.ok
    assert result.error


def test_collect_creates_destination_dir(tmp_path):
    target = tmp_path / "new" / "deep"
    ssh = _FakeSSH({"wc -c": (0, "10", "")})
    result = asyncio.run(collect_logs(_session(ssh), target))
    assert target.is_dir()
    assert result.ok


# ── Скриншот ────────────────────────────────────────────────────────


def test_screenshot_returns_last_file(tmp_path):
    ssh = _FakeSSH({"ls -1": (0, "/home/tc/screenshot_1.png\n/home/tc/screenshot_2.png", "")})
    path = asyncio.run(take_screenshot(_session(ssh)))
    assert path == "/home/tc/screenshot_2.png"
    assert "imlib2_grab" in ssh.commands[0]


def test_screenshot_returns_empty_on_failure():
    ssh = _FakeSSH({"imlib2_grab": (1, "", "not found")})
    assert asyncio.run(take_screenshot(_session(ssh))) == ""


# ── Ход работы ──────────────────────────────────────────────────────


def _collect_with_progress(tmp_path, responses):
    events: list = []
    ssh = _FakeSSH(responses)
    result = asyncio.run(
        collect_logs(_session(ssh), tmp_path, on_progress=events.append)
    )
    return result, events


def test_progress_reports_all_stages(tmp_path):
    _result, events = _collect_with_progress(
        tmp_path, {"wc -c": (0, "1024", ""), "find": (0, "3\n", "")}
    )
    stages = {e.stage for e in events}
    assert {"measure", "count", "pack", "download", "done"} <= stages


def test_progress_pack_percent_follows_file_count(tmp_path):
    tar_listing = "a.log\nb.log\nc.log\nd.log\n"
    _result, events = _collect_with_progress(
        tmp_path, {"wc -c": (0, "1024", ""), "find": (0, "4\n", ""), "tar -czvf": (0, tar_listing, "")}
    )
    pack = [e for e in events if e.stage == "pack" and e.percent >= 0]
    assert [e.percent for e in pack] == [25, 50, 75, 99]
    assert "1 из 4" in pack[0].detail
    assert "4 из 4" in pack[-1].detail


def test_progress_download_reaches_hundred(tmp_path):
    result, events = _collect_with_progress(tmp_path, {"wc -c": (0, "1024", "")})
    done = [e for e in events if e.stage == "done"]
    assert done and done[0].percent == 100
    assert result.archive.name in done[0].detail


def test_progress_elapsed_grows(tmp_path):
    _result, events = _collect_with_progress(tmp_path, {"wc -c": (0, "1024", "")})
    assert events[0].elapsed <= events[-1].elapsed


def test_progress_uses_indeterminate_when_count_unknown(tmp_path):
    _result, events = _collect_with_progress(
        tmp_path, {"wc -c": (0, "1024", ""), "find": (0, "0\n", ""), "tar -czvf": (0, "x\n" * 30, "")}
    )
    pack = [e for e in events if e.stage == "pack"]
    assert pack
    assert all(e.percent == -1 for e in pack)


def test_count_command_counts_dirs_too():
    """tar -v печатает и каталоги, поэтому -type f занижал бы итог."""
    cmd = count_files_command()
    assert "-type f" not in cmd
    assert cmd.startswith("find ")
    assert cmd.endswith("2>/dev/null | wc -l")
    for src in LOG_SOURCES:
        assert f'"{src}"' in cmd


def test_packed_count_matches_total_on_real_layout(tmp_path):
    tar_listing = "".join(f"f{i}\n" for i in range(850))
    result, _events = _collect_with_progress(
        tmp_path,
        {"wc -c": (0, "1024", ""), "find": (0, "850\n", ""), "tar -czvf": (0, tar_listing, "")},
    )
    assert result.total_files == 850
    assert result.packed_files == 850
