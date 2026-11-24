"""Officer accounts: password hashing, login sessions and a simple login lockout.

Passwords are hashed with scrypt (stdlib). Session tokens are random; only their
SHA-256 is stored, so a database leak does not expose usable tokens.
"""
import hashlib
import hmac
import secrets
import threading
import time

SESSION_DAYS = 14
MIN_PASSWORD_LEN = 8

_SCRYPT = dict(n=2**14, r=8, p=1, dklen=32)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        # Spend the same time as a real check so unknown badges are not detectable.
        hashlib.scrypt(password.encode(), salt=b"\0" * 16, **_SCRYPT)
        return False
    try:
        _, salt_hex, dk_hex = stored.split("$")
    except ValueError:
        return False
    dk = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), **_SCRYPT)
    return hmac.compare_digest(dk, bytes.fromhex(dk_hex))


def new_token() -> tuple[str, str]:
    """Return (token for the client, hash to store)."""
    token = secrets.token_urlsafe(32)
    return token, token_hash(token)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class LoginLimiter:
    """Locks a badge for LOCK_SECONDS after MAX_FAILS wrong passwords.

    In memory: fine for a single server instance; resets on restart.
    """
    MAX_FAILS = 5
    LOCK_SECONDS = 15 * 60

    def __init__(self):
        self._fails: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def locked_for(self, badge: str) -> int:
        with self._lock:
            count, since = self._fails.get(badge, (0, 0.0))
            if count < self.MAX_FAILS:
                return 0
            left = int(since + self.LOCK_SECONDS - time.time())
            if left <= 0:
                self._fails.pop(badge, None)
                return 0
            return left

    def fail(self, badge: str) -> None:
        with self._lock:
            count, _ = self._fails.get(badge, (0, 0.0))
            self._fails[badge] = (count + 1, time.time())

    def reset(self, badge: str) -> None:
        with self._lock:
            self._fails.pop(badge, None)
