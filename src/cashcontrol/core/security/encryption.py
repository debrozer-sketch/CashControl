"""
Encryption module — secure password storage using Fernet symmetric encryption.

Passwords are stored encrypted in settings.json. Master key is stored in
data/.keystore: on Windows the Fernet key is sealed with DPAPI
(win32crypt.CryptProtectData); on Linux it is stored in the OS keyring
(keyring/libsecret) with a fallback to a plaintext file (chmod 0600).
A legacy plaintext base64 key found there is migrated on first load.
On first use, master key is generated.
"""

from __future__ import annotations

import os
import platform
from typing import TYPE_CHECKING

from cryptography.fernet import Fernet, InvalidToken

from cashcontrol.infrastructure.audit_logger import get_logger
from cashcontrol.infrastructure.path_resolver import get_keystore_file

if TYPE_CHECKING:
    from pathlib import Path

logger = get_logger()

_DPAPI_ENTROPY = b"CashControl.keystore.v1"
_KEYRING_SERVICE = "cashcontrol"
_KEYRING_KEY = "master_key"


def _dpapi_available() -> bool:
    if platform.system() != "Windows":
        return False
    try:
        import win32crypt  # noqa: F401
        return True
    except ImportError:
        return False


def _dpapi_protect(data: bytes) -> bytes:
    import win32crypt
    return win32crypt.CryptProtectData(data, "CashControl", _DPAPI_ENTROPY, None, None, 0)


def _dpapi_unprotect(blob: bytes) -> bytes | None:
    try:
        import win32crypt
        _, data = win32crypt.CryptUnprotectData(blob, _DPAPI_ENTROPY, None, None, 0)
        return data
    except Exception:
        return None


def _keyring_available() -> bool:
    """Check if the keyring module is available for Linux."""
    try:
        import keyring  # noqa: F401
        return True
    except ImportError:
        return False


def _keyring_get() -> bytes | None:
    """Retrieve master key from OS keyring (Linux: libsecret/KWallet)."""
    if not _keyring_available():
        return None
    try:
        import keyring
        return keyring.get_password(_KEYRING_SERVICE, _KEYRING_KEY)
    except Exception:
        return None


def _keyring_set(data: bytes) -> None:
    """Store master key in OS keyring (Linux: libsecret/KWallet)."""
    if not _keyring_available():
        return
    try:
        import keyring
        keyring.set_password(_KEYRING_SERVICE, _KEYRING_KEY, data.decode("utf-8"))
    except Exception as e:
        logger.warning(f"Failed to store key in keyring: {e}")


def _secure_store_key(key: bytes, path: Path) -> None:
    """Write key to file with secure permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_bytes(key)
    os.chmod(str(tmp_path), 0o600)
    tmp_path.rename(path)


class EncryptionManager:
    """
    Manages encryption/decryption of sensitive data using Fernet.

    Singleton pattern — one master key per application instance.
    Master key is stored in data/.keystore file, optionally protected
    by OS keyring (Linux) or DPAPI (Windows).
    """

    _instance: EncryptionManager | None = None
    _fernet: Fernet | None = None
    _keystore_path: Path

    def __new__(cls) -> EncryptionManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._keystore_path = get_keystore_file()
        self._fernet = self._load_or_create_key()

    def _load_or_create_key(self) -> Fernet:
        """
        Load master key from keystore or create new one.

        Loading order:
        1. DPAPI-sealed blob (Windows)
        2. OS keyring (Linux/macOS with keyring installed)
        3. Plaintext base64 Fernet key (legacy, migrated to OS keyring)

        A corrupted existing keystore raises loudly instead of silently
        regenerating (which would make all stored passwords undecryptable).

        Returns:
            Fernet instance with master key

        Raises:
            RuntimeError: If an existing keystore cannot be decrypted
        """
        if self._keystore_path.exists():
            return Fernet(self._load_key_bytes())

        key = Fernet.generate_key()
        self._write_key_bytes(key)
        logger.info("New master key generated and stored")
        return Fernet(key)

    def _load_key_bytes(self) -> bytes:
        raw = self._keystore_path.read_bytes()

        # Try DPAPI (Windows)
        if _dpapi_available():
            key = _dpapi_unprotect(raw)
            if key is not None:
                try:
                    Fernet(key)
                except Exception as e:
                    raise RuntimeError(self._corrupt_message()) from e
                logger.debug("Master key loaded from DPAPI-protected keystore")
                return key

        # Try keyring (Linux/macOS)
        keyring_str = _keyring_get()
        if keyring_str is not None:
            keyring_bytes = keyring_str.encode("utf-8")
            try:
                Fernet(keyring_bytes)
            except Exception as e:
                raise RuntimeError(self._corrupt_message()) from e
            logger.debug("Master key loaded from OS keyring")
            return keyring_bytes

        # Legacy plaintext base64 key
        try:
            Fernet(raw)
        except Exception as e:
            raise RuntimeError(self._corrupt_message()) from e

        # Migrate to OS keyring or secure file
        if _dpapi_available():
            logger.info("Migrating legacy plaintext keystore to DPAPI")
            blob = _dpapi_protect(raw)
            self._keystore_path.write_bytes(blob)
        elif _keyring_available():
            logger.info("Migrating legacy plaintext keystore to OS keyring")
            _keyring_set(raw)
            self._keystore_path.unlink(missing_ok=True)
        else:
            logger.warning(
                "No OS keyring available, master key kept in secure file (chmod 0600)"
            )
            _secure_store_key(raw, self._keystore_path)
        return raw

    def _write_key_bytes(self, key: bytes) -> None:
        if _dpapi_available():
            blob = _dpapi_protect(key)
            self._keystore_path.write_bytes(blob)
            self._set_keystore_hidden(True)
        elif _keyring_available():
            _keyring_set(key)
            self._keystore_path.parent.mkdir(parents=True, exist_ok=True)
            self._keystore_path.unlink(missing_ok=True)
        else:
            _secure_store_key(key, self._keystore_path)

    def _set_keystore_hidden(self, hidden: bool) -> None:
        try:
            if platform.system() == "Windows":
                import ctypes
                attribute = 0x02 if hidden else 0x80  # HIDDEN / NORMAL
                ctypes.windll.kernel32.SetFileAttributesW(
                    str(self._keystore_path), attribute
                )
        except Exception as e:
            logger.debug(f"Could not update keystore file attributes: {e}")

    @staticmethod
    def _corrupt_message() -> str:
        return (
            "Файл data/.keystore повреждён или не расшифровывается. "
            "Сохранённые пароли станут нечитаемы при замене ключа. "
            "Если это ожидаемо — удалите .keystore и заново введите пароли; "
            "иначе восстановите файл из резервной копии."
        )

    def encrypt(self, plaintext: str) -> str:
        """Encrypt string to base64-encoded ciphertext."""
        if not plaintext:
            return ""
        try:
            encrypted_bytes = self._fernet.encrypt(plaintext.encode("utf-8"))
            return encrypted_bytes.decode("ascii")
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            raise

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt base64-encoded ciphertext to plaintext."""
        if not ciphertext:
            return ""
        try:
            decrypted_bytes = self._fernet.decrypt(ciphertext.encode("ascii"))
            return decrypted_bytes.decode("utf-8")
        except InvalidToken:
            logger.error("Decryption failed: invalid token or wrong key")
            raise
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            raise

    def encrypt_list(self, plaintexts: list[str]) -> list[str]:
        """Encrypt list of strings."""
        return [self.encrypt(text) for text in plaintexts if text]

    def decrypt_list(self, ciphertexts: list[str]) -> list[str]:
        """Decrypt list of encrypted strings (skips invalid tokens)."""
        decrypted = []
        for cipher in ciphertexts:
            if not cipher:
                continue
            try:
                decrypted.append(self.decrypt(cipher))
            except InvalidToken:
                logger.warning("Skipping invalid encrypted token")
                continue
        return decrypted

    @classmethod
    def _reset_singleton(cls) -> None:
        """Reset singleton (for testing only)."""
        cls._instance = None


# ── Convenience functions ─────────────────────────────


def encrypt_password(password: str) -> str:
    """Encrypt password (convenience function)."""
    manager = EncryptionManager()
    return manager.encrypt(password)


def decrypt_password(encrypted: str) -> str:
    """Decrypt password (convenience function)."""
    manager = EncryptionManager()
    return manager.decrypt(encrypted)


def encrypt_passwords(passwords: list[str]) -> list[str]:
    """Encrypt list of passwords."""
    manager = EncryptionManager()
    return manager.encrypt_list(passwords)


def decrypt_passwords(encrypted_list: list[str]) -> list[str]:
    """Decrypt list of passwords."""
    manager = EncryptionManager()
    return manager.decrypt_list(encrypted_list)
