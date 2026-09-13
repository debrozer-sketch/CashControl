"""Integration tests for the built-in Remote Files manager launcher."""

from __future__ import annotations

from cashcontrol.builtin.file_manager_launcher import (
    builtin_file_manager_root,
    file_manager_available,
    should_use_builtin_files,
)


def test_should_use_builtin_files_unset_or_missing():
    assert should_use_builtin_files(None) is True
    assert should_use_builtin_files("") is True
    assert should_use_builtin_files("   ") is True
    assert should_use_builtin_files("Z:\\missing\\WinSCP.exe") is True


def test_should_use_builtin_files_existing_file(tmp_path):
    exe = tmp_path / "WinSCP.exe"
    exe.write_bytes(b"MZ")
    assert should_use_builtin_files(str(exe)) is False


def test_builtin_file_manager_package_available():
    assert file_manager_available() is True
    assert (builtin_file_manager_root() / "gui" / "window.py").is_file()
