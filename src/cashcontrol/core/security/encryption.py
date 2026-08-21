"""
Encryption module — secure password storage using Fernet symmetric encryption.

Passwords are stored encrypted in settings.json. Master key is stored in
data/.keystore (base64-encoded). On first use, master key is generated.

Usage:
    from cashcontrol.core.security.encryption import encrypt_password, decrypt_password

    encrypted = encrypt_password("my_secret_password")
    # Store encrypted in config

    decrypted = decrypt_password(encrypted)
    # Use decrypted password
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cryptography.fernet import Fernet, InvalidToken

from cashcontrol.infrastructure.audit_logger import get_logger
from cashcontrol.infrastructure.path_resolver import get_keystore_file

if TYPE_CHECKING:
    from pathlib import Path

logger = get_logger()


class EncryptionManager:
    """
    Manages encryption/decryption of sensitive data using Fernet.

    Singleton pattern — one master key per application instance.
    Master key is stored in data/.keystore file.
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

        Returns:
            Fernet instance with master key
        """
        if self._keystore_path.exists():
            try:
                key_data = self._keystore_path.read_bytes()
                # Validate key format
                Fernet(key_data)
                logger.debug("Master key loaded from keystore")
                return Fernet(key_data)
            except Exception as e:
                logger.warning(f"Corrupted keystore, regenerating: {e}")
                # Fallthrough to create new key

        # Generate new key
        key = Fernet.generate_key()
        self._keystore_path.parent.mkdir(parents=True, exist_ok=True)
        self._keystore_path.write_bytes(key)

        # Protect keystore file (hide on Windows)
        try:
            import platform

            if platform.system() == "Windows":
                import ctypes

                FILE_ATTRIBUTE_HIDDEN = 0x02
                ctypes.windll.kernel32.SetFileAttributesW(
                    str(self._keystore_path), FILE_ATTRIBUTE_HIDDEN
                )
        except Exception as e:
            logger.debug(f"Could not hide keystore file: {e}")

        logger.info("New master key generated and stored")
        return Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt string to base64-encoded ciphertext.

        Args:
            plaintext: String to encrypt

        Returns:
            Base64-encoded encrypted string (safe to store in JSON)

        Example:
            encrypted = manager.encrypt("my_password")
            # Returns: "gAAAAABh1..."
        """
        if not plaintext:
            return ""

        try:
            encrypted_bytes = self._fernet.encrypt(plaintext.encode("utf-8"))
            return encrypted_bytes.decode("ascii")
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            raise

    def decrypt(self, ciphertext: str) -> str:
        """
        Decrypt base64-encoded ciphertext to plaintext.

        Args:
            ciphertext: Encrypted string from encrypt()

        Returns:
            Decrypted plaintext string

        Raises:
            InvalidToken: If ciphertext is corrupted or was encrypted with different key

        Example:
            decrypted = manager.decrypt("gAAAAABh1...")
            # Returns: "my_password"
        """
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
        """
        Encrypt list of strings.

        Args:
            plaintexts: List of strings to encrypt

        Returns:
            List of encrypted strings
        """
        return [self.encrypt(text) for text in plaintexts if text]

    def decrypt_list(self, ciphertexts: list[str]) -> list[str]:
        """
        Decrypt list of encrypted strings.

        Args:
            ciphertexts: List of encrypted strings

        Returns:
            List of decrypted strings (skips invalid tokens)
        """
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
    """
    Encrypt password (convenience function).

    Args:
        password: Plaintext password

    Returns:
        Encrypted password string
    """
    manager = EncryptionManager()
    return manager.encrypt(password)


def decrypt_password(encrypted: str) -> str:
    """
    Decrypt password (convenience function).

    Args:
        encrypted: Encrypted password string

    Returns:
        Plaintext password

    Raises:
        InvalidToken: If encrypted string is invalid
    """
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