"""Standalone command-line interface for the Remote Files core (``rfiles``)."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import asyncssh

from cashcontrol.builtin.file_manager import __version__
from cashcontrol.builtin.file_manager.backends import (
    SFTP_SUBSYSTEM_TIMEOUT,
    ScpShellBackend,
    SftpBackend,
    SSHScpProvider,
    SSHShellRunner,
    connect_with_tofu,
)
from cashcontrol.builtin.file_manager.models import (
    HostKeyMismatchError,
    OperationCancelledError,
    OverwritePolicy,
    RemoteAuthError,
    RemoteConnectionError,
    RemoteFileInfo,
    RemoteFilesError,
    RemoteNotFoundError,
    RemotePermissionError,
    TransferOptions,
    basename_remote,
)
from cashcontrol.builtin.file_manager.service import RemoteFileService

if TYPE_CHECKING:
    from cashcontrol.builtin.file_manager.models import RemoteFsBackend

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_CONNECT = 3
EXIT_AUTH = 4
EXIT_HOSTKEY = 5
EXIT_NOT_FOUND = 6
EXIT_PERMISSION = 7
EXIT_ABORTED = 130


def _print_error(message: str) -> None:
    print(f"rfiles: ошибка: {message}", file=sys.stderr)


def error_exit(exc: BaseException) -> int:
    for cls, code in (
        (RemoteAuthError, EXIT_AUTH),
        (HostKeyMismatchError, EXIT_HOSTKEY),
        (RemoteConnectionError, EXIT_CONNECT),
        (RemoteNotFoundError, EXIT_NOT_FOUND),
        (RemotePermissionError, EXIT_PERMISSION),
        (OperationCancelledError, EXIT_ABORTED),
    ):
        if isinstance(exc, cls):
            return code
    return EXIT_ERROR


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def add_connection_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("подключение")
    group.add_argument("--host", default=None, help="удалённый хост (обязательно)")
    group.add_argument("--port", type=int, default=22, help="порт SSH (по умолчанию: 22)")
    group.add_argument("--user", default=os.environ.get("RFILES_USER", "root"), help="пользователь SSH (env RFILES_USER)")
    group.add_argument("--password", default=os.environ.get("RFILES_PASSWORD"), help="пароль SSH (env RFILES_PASSWORD)")
    group.add_argument("--key-file", default=None, help="путь к закрытому ключу SSH")
    group.add_argument("--protocol", choices=("auto", "sftp", "scp"), default="auto")
    group.add_argument("--known-hosts", default=None, help="файл known_hosts (по умолчанию: RFILES_CONFIG_DIR)")
    group.add_argument("--timeout", type=float, default=15.0, help="таймаут подключения/команд в секундах (по умолчанию: 15)")
    group.add_argument("--json", action="store_true", help="выдавать машиночитаемый JSON")
    group.add_argument("--verbose", "-v", action="count", default=0, help="показывать прогресс по файлам")


def add_overwrite_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("политика перезаписи")
    group.add_argument("--skip-existing", action="store_true", help="пропускать уже существующие пути")
    group.add_argument(
        "--overwrite-if-newer",
        action="store_true",
        help="перезаписывать, только если источник новее",
    )
    group.add_argument("--no-atomic", action="store_true", help="отключить атомарную передачу через временный файл")


def overwrite_options(args: argparse.Namespace) -> TransferOptions:
    if args.overwrite_if_newer:
        policy = OverwritePolicy.OVERWRITE_IF_NEWER
    elif args.skip_existing:
        policy = OverwritePolicy.SKIP
    else:
        policy = OverwritePolicy.OVERWRITE
    return TransferOptions(overwrite_policy=policy, atomic=not args.no_atomic)


def info_row(info: RemoteFileInfo) -> str:
    mtime = info.modified_at.isoformat(timespec="minutes") if info.modified_at else "-"
    target = f" -> {info.link_target}" if info.link_target else ""
    suffix = "/" if info.is_dir else ("@" if info.is_symlink else "")
    return (
        f"{info.mode_str} {info.owner or '-':>8} {info.group or '-':>8} "
        f"{info.size if info.size is not None else '-':>10} {mtime} {info.name}{suffix}{target}"
    )


async def _open_service(args: argparse.Namespace) -> tuple[RemoteFileService, asyncssh.SSHClientConnection]:
    conn = await connect_with_tofu(
        host=args.host,
        port=args.port,
        username=args.user,
        password=args.password,
        key_file=args.key_file,
        known_hosts=args.known_hosts,
        timeout=args.timeout,
    )
    if args.protocol in ("auto", "sftp"):
        try:
            probe = await asyncio.wait_for(conn.start_sftp_client(), SFTP_SUBSYSTEM_TIMEOUT)
            probe.close()
            backend: RemoteFsBackend = SftpBackend(connection=conn, own_connection=True)
            return RemoteFileService(backend, close_backend=True), conn
        except (OSError, asyncssh.Error):
            if args.protocol == "sftp":
                raise RemoteConnectionError("SFTP-подсистема недоступна на удалённом хосте") from None
    runner = SSHShellRunner(conn, timeout=args.timeout)
    backend = ScpShellBackend(runner, SSHScpProvider(conn), timeout=args.timeout)
    return RemoteFileService(backend, close_backend=False), conn


async def _close(service: RemoteFileService, conn: asyncssh.SSHClientConnection) -> None:
    await service.close()
    if not conn.is_closed():
        conn.close()
        await conn.wait_closed()


async def cmd_ls(args: argparse.Namespace) -> int:
    service, conn = await _open_service(args)
    try:
        items = await service.list_dir(args.path or "/")
        if args.json:
            print(_json([item.model_dump(mode="json") for item in items]))
        else:
            items.sort(key=lambda item: (not item.is_dir, item.name.lower()))
            for item in items:
                print(info_row(item))
        return EXIT_OK
    finally:
        await _close(service, conn)


async def cmd_stat(args: argparse.Namespace) -> int:
    service, conn = await _open_service(args)
    try:
        info = await service.stat(args.path)
        if args.json:
            print(_json(info.model_dump(mode="json")))
        else:
            print(info_row(info))
        return EXIT_OK
    finally:
        await _close(service, conn)


async def cmd_mkdir(args: argparse.Namespace) -> int:
    service, conn = await _open_service(args)
    try:
        await service.mkdir(args.path, mode=_parse_mode(args.mode), create_parents=args.parents)
        return EXIT_OK
    finally:
        await _close(service, conn)


async def cmd_mv(args: argparse.Namespace) -> int:
    service, conn = await _open_service(args)
    try:
        await service.rename(args.source, args.destination)
        return EXIT_OK
    finally:
        await _close(service, conn)


async def cmd_chmod(args: argparse.Namespace) -> int:
    service, conn = await _open_service(args)
    mode = _parse_mode(args.mode)
    try:
        for path in args.paths:
            await service.chmod(path, mode)
        return EXIT_OK
    finally:
        await _close(service, conn)


async def cmd_rm(args: argparse.Namespace) -> int:
    service, conn = await _open_service(args)
    try:
        for path in args.paths:
            info = await service.stat(path)
            if info.is_dir and not args.recursive:
                raise RemotePermissionError(f"{path} — каталог; используйте --recursive")
        await service.remove(args.paths, recursive=args.recursive, on_confirm=_deletion_confirmer(args))
        return EXIT_OK
    finally:
        await _close(service, conn)


def _deletion_confirmer(args: argparse.Namespace):
    def confirm(paths: list[str], recursive: bool) -> bool:
        if args.yes:
            return True
        if not sys.stdin.isatty():
            _print_error("для рекурсивного удаления в неинтерактивном режиме нужен --yes")
            return False
        reply = input(f"Удалить {len(paths)} путей (-и) рекурсивно ({', '.join(paths)})? [y/N]: ")
        return reply.strip().lower() in {"y", "yes"}

    return confirm


async def cmd_get(args: argparse.Namespace) -> int:
    service, conn = await _open_service(args)
    sources = args.operands[:-1]
    destination = Path(args.operands[-1])
    options = overwrite_options(args)
    try:
        if len(sources) == 1 and not destination.is_dir():
            local_target = destination
            local_dir = destination.parent
            local_dir.mkdir(parents=True, exist_ok=True)
            result = await service.download(sources, local_dir, options, progress=_verbose_progress(args))
            if result.transferred_files and not result.failed_files and args.verbose:
                pass
            renamed = local_dir / basename_remote(sources[0])
            if renamed != local_target:
                _print_error("копирование нескольких файлов в одно имя не поддерживается")
                return EXIT_ERROR
        else:
            result = await service.download(sources, destination, options, progress=_verbose_progress(args))
        if result.failed_files:
            for error in result.errors:
                _print_error(error)
            return EXIT_ERROR
        return EXIT_OK
    finally:
        await _close(service, conn)


async def cmd_put(args: argparse.Namespace) -> int:
    service, conn = await _open_service(args)
    sources = args.operands[:-1]
    remote_dir = args.operands[-1]
    options = overwrite_options(args)
    try:
        await service.mkdir(remote_dir, create_parents=True)
        result = await service.upload([Path(p) for p in sources], remote_dir, options, progress=_verbose_progress(args))
        if result.failed_files:
            for error in result.errors:
                _print_error(error)
            return EXIT_ERROR
        return EXIT_OK
    finally:
        await _close(service, conn)


def _verbose_progress(args: argparse.Namespace):
    if args.verbose < 1:
        return None

    def progress(source: str, destination: str, copied: int, total: int) -> None:
        if total:
            print(f"{source} -> {destination}: {copied}/{total} байт", file=sys.stderr)

    return progress


def _parse_mode(raw: str | None) -> int | None:
    if raw is None:
        return None
    value = raw[2:] if raw.lower().startswith("0o") else raw
    return int(value, 8)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rfiles",
        description="Утилита передачи файлов по SFTP/SCP (в стиле WinSCP)",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, title="команды")

    ls_p = sub.add_parser("ls", help="список удалённого каталога")
    add_connection_args(ls_p)
    ls_p.add_argument("path", nargs="?", default="/")
    ls_p.set_defaults(func=cmd_ls)

    stat_p = sub.add_parser("stat", help="сведения об удалённом пути")
    add_connection_args(stat_p)
    stat_p.add_argument("path")
    stat_p.set_defaults(func=cmd_stat)

    mkdir_p = sub.add_parser("mkdir", help="создать удалённый каталог")
    add_connection_args(mkdir_p)
    mkdir_p.add_argument("-p", "--parents", action="store_true", help="создавать родительские каталоги")
    mkdir_p.add_argument("--mode", default=None, help="восьмеричные права доступа, например 755")
    mkdir_p.add_argument("path")
    mkdir_p.set_defaults(func=cmd_mkdir)

    mv_p = sub.add_parser("mv", help="переименовать/переместить удалённый путь")
    add_connection_args(mv_p)
    mv_p.add_argument("source")
    mv_p.add_argument("destination")
    mv_p.set_defaults(func=cmd_mv)

    chmod_p = sub.add_parser("chmod", help="изменить права на удалённом объекте")
    add_connection_args(chmod_p)
    chmod_p.add_argument("mode", help="восьмеричные права доступа, например 755")
    chmod_p.add_argument("paths", nargs="+")
    chmod_p.set_defaults(func=cmd_chmod)

    rm_p = sub.add_parser("rm", help="удалить удалённые пути")
    add_connection_args(rm_p)
    rm_p.add_argument("-r", "--recursive", action="store_true", help="удалять каталоги рекурсивно")
    rm_p.add_argument("--yes", action="store_true", help="не запрашивать подтверждения")
    rm_p.add_argument("paths", nargs="+")
    rm_p.set_defaults(func=cmd_rm)

    get_p = sub.add_parser("get", help="копировать удалённые пути на локальную машину")
    add_connection_args(get_p)
    add_overwrite_args(get_p)
    get_p.add_argument("operands", nargs="+", metavar="REMOTE_LOCAL", help="<удалённые> пути, затем локальный адресат")
    get_p.set_defaults(func=cmd_get)

    put_p = sub.add_parser("put", help="копировать локальные пути в удалённый каталог")
    add_connection_args(put_p)
    add_overwrite_args(put_p)
    put_p.add_argument("operands", nargs="+", metavar="LOCAL_REMOTE", help="<локальные> пути, затем удалённый каталог")
    put_p.set_defaults(func=cmd_put)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.host:
        parser.error("требуется --host")
    try:
        return asyncio.run(args.func(args))
    except KeyboardInterrupt:
        return EXIT_ABORTED
    except asyncio.CancelledError:
        return EXIT_ABORTED
    except RemoteFilesError as exc:
        _print_error(str(exc))
        return error_exit(exc)


if __name__ == "__main__":
    sys.exit(main())
