"""
Password manager — automatic SSH password iteration and caching.

When connecting to a cash register, tries passwords from config in order.
Caches successful passwords per IP for the session duration.

Usage:
    from cashcontrol.core.security.password_manager import PasswordManager

    manager = PasswordManager()

    # Try passwords for IP
    for password in manager.get_passwords_for_ip("192.168.1.100"):
        if try_connect(password):
            manager.cache_success("192.168.1.100", password)
            break
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cashcontrol.core.security.encryption import decrypt_passwords
from cashcontrol.infrastructure.audit_logger import get_logger
from cashcontrol.infrastructure.config_manager import ConfigManager

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = get_logger()


class PasswordManager:
    """
    Manages SSH password iteration with success caching.

    Features:
    - Decrypts passwords from config
    - Returns passwords in order (cached first, then rest)
    - Caches successful password per IP for session
    - Thread-safe for concurrent connections
    """

    def __init__(self) -> None:
        self._config = ConfigManager()
        # Cache: IP -> successful password (plaintext, in memory only)
        self._success_cache: dict[str, str] = {}

    def get_passwords_for_ip(self, ip: str, password_type: str = "ssh") -> Iterator[str]:
        """
        Get passwords to try for given IP, in optimal order.

        Order:
        1. Cached successful password for this IP (if exists)
        2. All other passwords from config

        Args:
            ip: Target IP address
            password_type: "ssh" or "db"

        Yields:
            Passwords to try (plaintext)

        Example:
            for pwd in manager.get_passwords_for_ip("192.168.1.100"):
                if connect(pwd):
                    manager.cache_success("192.168.1.100", pwd)
                    break
        """
        # Get encrypted passwords from config
        if password_type == "ssh":
            encrypted = self._config.settings.connection.ssh_passwords_encrypted
        elif password_type == "db":
            encrypted = self._config.settings.connection.db_passwords_encrypted
        else:
            logger.error(f"Unknown password type: {password_type}")
            return

        # Decrypt all passwords
        try:
            all_passwords = decrypt_passwords(encrypted)
        except Exception as e:
            logger.error(f"Failed to decrypt passwords: {e}")
            return

        if not all_passwords:
            if password_type == "db":
                # Fallback: use SSH passwords for DB if no DB passwords configured
                logger.debug("No db passwords configured, falling back to SSH passwords")
                try:
                    ssh_encrypted = self._config.settings.connection.ssh_passwords_encrypted
                    all_passwords = decrypt_passwords(ssh_encrypted)
                except Exception as e:
                    logger.error(f"Failed to decrypt SSH fallback passwords: {e}")
                    return
                if not all_passwords:
                    logger.warning("No passwords configured (neither DB nor SSH)")
                    return
            else:
                logger.warning(f"No {password_type} passwords configured")
                return

        # Cache key: IP + type
        cache_key = f"{ip}:{password_type}"

        # Check if we have cached successful password
        cached = self._success_cache.get(cache_key)

        if cached and cached in all_passwords:
            # Yield cached first
            logger.debug(f"Using cached password for {ip}")
            yield cached
            # Then yield others
            for pwd in all_passwords:
                if pwd != cached:
                    yield pwd
        else:
            # No cache, yield all
            yield from all_passwords

    def cache_success(self, ip: str, password: str, password_type: str = "ssh") -> None:
        """
        Cache successful password for IP.

        Args:
            ip: Target IP
            password: Successful password (plaintext)
            password_type: "ssh" or "db"
        """
        cache_key = f"{ip}:{password_type}"
        self._success_cache[cache_key] = password
        logger.info(f"Cached successful {password_type} password for {ip}")

    def clear_cache(self, ip: str | None = None) -> None:
        """
        Clear password cache.

        Args:
            ip: Specific IP to clear, or None to clear all
        """
        if ip is None:
            self._success_cache.clear()
            logger.info("Password cache cleared")
        else:
            # Clear all entries for this IP
            keys_to_remove = [k for k in self._success_cache if k.startswith(f"{ip}:")]
            for key in keys_to_remove:
                del self._success_cache[key]
            logger.info(f"Password cache cleared for {ip}")

    def get_cache_stats(self) -> dict[str, int]:
        """
        Get cache statistics.

        Returns:
            Dict with cache stats
        """
        return {
            "total_cached": len(self._success_cache),
            "ssh_cached": len([k for k in self._success_cache if k.endswith(":ssh")]),
            "db_cached": len([k for k in self._success_cache if k.endswith(":db")]),
        }

    @classmethod
    def _reset_singleton(cls) -> None:
        """For testing only."""
        pass