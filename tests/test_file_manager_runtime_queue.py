"""Tests for transfer job chunking in the built-in file manager.

Regression guard: ``_chunk`` used to be a closure inside ``enqueue_upload``
only, while ``enqueue_download`` and ``enqueue_local_copy`` called the same
name at module level. Both raised ``NameError`` on their first invocation,
so downloading from a cash register and local-to-local copy were dead paths.
"""

from __future__ import annotations

import pytest

from cashcontrol.builtin.file_manager.gui import runtime


class RecordingQueue:
    """Minimal TransferQueue stand-in that records enqueued jobs."""

    def __init__(self) -> None:
        self.jobs: list[tuple[str, str, str]] = []

    def enqueue(self, operation: str, label: str, dest_dir: str, runner) -> str:
        self.jobs.append((operation, label, dest_dir))
        return f"job-{len(self.jobs)}"


class _Unused:
    """Placeholder for service/prompter args never reached by these tests."""


def test_chunk_splits_above_batch_size():
    paths = [f"f{i}" for i in range(5)]
    chunks = runtime._chunk(paths)
    assert [len(c) for c in chunks] == [3, 2]
    assert [p for c in chunks for p in c] == paths


@pytest.mark.parametrize("count", [0, 1, 2, 3, 4, 7, 10])
def test_chunk_preserves_all_paths_for_any_count(count):
    paths = [f"f{i}" for i in range(count)]
    chunks = runtime._chunk(paths)
    assert [p for c in chunks for p in c] == paths
    assert all(len(c) <= runtime._TRANSFER_BATCH for c in chunks)
    if count:
        assert sum(len(c) for c in chunks) == count


def test_enqueue_download_chunks_and_returns_first_job_id():
    queue = RecordingQueue()
    paths = [f"/home/tc/storage/f{i}.txt" for i in range(5)]

    first = runtime.enqueue_download(queue, _Unused(), _Unused(), paths, "/local")

    assert [op for op, _, _ in queue.jobs] == ["download", "download"]
    assert first == "job-1"


def test_enqueue_local_copy_chunks_and_returns_first_job_id():
    queue = RecordingQueue()
    paths = [f"C:/data/f{i}.txt" for i in range(4)]

    first = runtime.enqueue_local_copy(queue, paths, "C:/dest")

    assert [op for op, _, _ in queue.jobs] == ["copy", "copy"]
    assert first == "job-1"


def test_enqueue_upload_chunks_and_returns_first_job_id():
    queue = RecordingQueue()
    paths = [f"C:/data/f{i}.txt" for i in range(5)]

    first = runtime.enqueue_upload(queue, _Unused(), _Unused(), paths, "/home/tc/storage")

    assert [op for op, _, _ in queue.jobs] == ["upload", "upload"]
    assert first == "job-1"


@pytest.mark.parametrize(
    ("enqueue", "leading_count", "args"),
    [
        ("enqueue_download", 2, ("/local",)),
        ("enqueue_local_copy", 0, ("C:/dest",)),
        ("enqueue_upload", 2, ("/home/tc/storage",)),
    ],
)
def test_single_file_is_one_job(enqueue, leading_count, args):
    """A lone file must stay a single job — chunking must not split it."""
    queue = RecordingQueue()
    leading = (_Unused(), _Unused())[:leading_count]
    runtime.__dict__[enqueue](queue, *leading, ["/home/tc/storage/one.txt"], *args)
    assert len(queue.jobs) == 1
