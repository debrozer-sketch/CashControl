"""Remote Files: standalone SFTP/SCP file management core.

The package is deliberately free of any ``cashcontrol.*`` imports so it can be
used as a standalone library/CLI. Embedded usage goes through a thin adapter
layer inside this repository (``cashcontrol.builtin.file_manager_launcher``).
"""

from __future__ import annotations

from cashcontrol.builtin.file_manager.backends import HostKeyStore, default_config_dir
from cashcontrol.builtin.file_manager.models import (
    FileKind,
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
    TransferProgress,
    TransferResult,
    TransferStatus,
    UnsupportedByBackendError,
)
from cashcontrol.builtin.file_manager.service import (
    ConflictInfo,
    RemoteFileService,
    TransferJob,
    TransferQueue,
    auto_resolve,
    renamed_destination,
)

__version__ = "0.1.0"

__all__ = [
    "ConflictInfo",
    "FileKind",
    "HostKeyMismatchError",
    "HostKeyStore",
    "OperationCancelledError",
    "OverwritePolicy",
    "RemoteAuthError",
    "RemoteConnectionError",
    "RemoteFileInfo",
    "RemoteFileService",
    "RemoteFilesError",
    "RemoteNotFoundError",
    "RemotePermissionError",
    "TransferJob",
    "TransferOptions",
    "TransferProgress",
    "TransferQueue",
    "TransferResult",
    "TransferStatus",
    "UnsupportedByBackendError",
    "__version__",
    "auto_resolve",
    "default_config_dir",
    "renamed_destination",
]
