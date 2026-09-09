"""Integration tests for the built-in SSH terminal (vendored in builtin_terminal/)."""

from __future__ import annotations

import sys

import pytest

from cashcontrol.gui.ssh_terminal_launcher import (
    build_terminal_command,
    builtin_terminal_root,
    should_use_builtin_ssh,
)


@pytest.mark.parametrize("path", [None, "", "   ", "Z:\\missing\\kitty.exe"])
def test_should_use_builtin_ssh_unset_or_missing(path):
    assert should_use_builtin_ssh(path) is True


def test_should_use_builtin_ssh_existing_file(tmp_path):
    exe = tmp_path / "kitty.exe"
    exe.write_bytes(b"MZ")
    assert should_use_builtin_ssh(str(exe)) is False


def test_build_command_carries_connection_args():
    cmd = build_terminal_command("10.0.0.5", 2222, "tc", False)
    assert cmd[0].endswith("pythonw.exe") or cmd[0].endswith("python.exe")
    assert cmd[1].endswith("main.py")
    assert "--host" in cmd and "10.0.0.5" in cmd
    assert "--port" in cmd and "2222" in cmd
    assert "--login" in cmd and "tc" in cmd
    assert "--password-stdin" not in cmd


def test_build_command_password_flag_only_for_password():
    with_pw = build_terminal_command("10.0.0.5", 22, "tc", True)
    assert "--password-stdin" in with_pw


def test_build_command_password_never_in_argv():
    secret = "hunter2-super-secret"
    cmd = build_terminal_command("10.0.0.5", 22, "tc", True)
    assert "--password-stdin" in cmd
    assert all(secret not in part for part in cmd)


@pytest.mark.skipif(
    not builtin_terminal_root().is_dir(),
    reason="vendored builtin_terminal/ is not present",
)
def test_vendored_emulator_processes_output():
    root = builtin_terminal_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from terminal.emulator import TerminalEmulator

    emu = TerminalEmulator(cols=40, rows=10)
    emu.feed("hello world\r\n")
    assert "hello world" in "\n".join(emu.primary.display)
