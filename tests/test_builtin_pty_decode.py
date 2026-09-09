"""Unit tests for the vendored PTY decoding (UTF-8 chunk splits + cp1251)."""

from __future__ import annotations

import sys

import pytest

from cashcontrol.gui.ssh_terminal_launcher import builtin_terminal_root

pytestmark = pytest.mark.skipif(
    not builtin_terminal_root().is_dir(),
    reason="vendored builtin_terminal/ is not present",
)


@pytest.fixture(scope="module")
def pty_stream():
    root = builtin_terminal_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from core.pty import PtyStream

    return PtyStream(conn=None)


def test_decode_plain_utf8(pty_stream):
    text = "OK \u043f\u0440\u0438\u0432\u0435\u0442"
    assert pty_stream._decode(text.encode("utf-8")) == text
    assert pty_stream._partial_utf8 == b""


def test_decode_split_cyrillic_across_chunks(pty_stream):
    payload = "\u041f\u0440\u0438\u0432\u0435\u0442".encode("utf-8")  # "Привет"
    cut = 1  # рву ровно после D0 (2-байтовый символ)
    first = pty_stream._decode(payload[:cut])
    second = pty_stream._decode(payload[cut:])
    assert first == ""
    assert pty_stream._partial_utf8 == b""
    assert second == "\u041f\u0440\u0438\u0432\u0435\u0442"


def test_decode_pure_cp1251_no_false_split(pty_stream):
    cp1251 = b"\xcf\xf0\xe8\xe2\xe5\xf2"  # "Привет" в cp1251
    assert pty_stream._decode(cp1251) == "\u041f\u0440\u0438\u0432\u0435\u0442"
    assert pty_stream._partial_utf8 == b""


def test_is_truncated_tail():
    root = builtin_terminal_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from core.pty import PtyStream

    def err(data: bytes, reason: str) -> UnicodeDecodeError:
        start = next(
            (i for i, b in enumerate(data) if b >= 0x80), 0
        )
        return UnicodeDecodeError("utf-8", data, start, len(data), reason)

    assert PtyStream._is_truncated_tail(b"\xe2\x82", err(b"\xe2\x82", "unexpected end of data"))
    assert PtyStream._is_truncated_tail(b"\xd0", err(b"\xd0", "unexpected end of data"))

    # континуация после ведущего байта сломанная — это не разрыв чанка
    assert not PtyStream._is_truncated_tail(b"\xd0A", err(b"\xd0A", "invalid continuation byte"))
    # настоящий cp1251: end < len(data) — не разрыв
    assert not PtyStream._is_truncated_tail(
        b"\xcf\xf0\xe8\xe2\xe5\xf2", err(b"\xcf\xf0\xe8\xe2\xe5\xf2", "invalid start byte")
    )
