"""Password hashing, auth tokens, reset tokens and uid encoding.

The stored password format is ``pbkdf2_sha256$<iterations>$<salt>$<b64>``
and it is reproduced byte for byte: rows already in the database were
written by the baseline stack and must keep verifying.
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import math
import secrets
from typing import Any, Callable, Optional

RANDOM_STRING_CHARS = (
    'abcdefghijklmnopqrstuvwxyz'
    'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    '0123456789'
)

ALGORITHM = 'pbkdf2_sha256'
ITERATIONS = 600000
DIGEST = hashlib.sha256
UNUSABLE_PASSWORD_PREFIX = '!'
UNUSABLE_PASSWORD_SUFFIX_LENGTH = 40

#: Reset links stay valid for three days, as on the baseline.
PASSWORD_RESET_TIMEOUT = 259200


def get_random_string(length: int, allowed_chars: str = RANDOM_STRING_CHARS) -> str:
    return ''.join(secrets.choice(allowed_chars) for _ in range(length))


def salt() -> str:
    char_count = len(RANDOM_STRING_CHARS)
    # 128 bits of entropy, matching the baseline default.
    n = math.ceil(128 / (math.log(char_count) / math.log(2)))
    return get_random_string(n)


def pbkdf2(password, salt_value, iterations: int, dklen: int = 0, digest=None) -> bytes:
    digest = digest or DIGEST
    dklen = dklen or None
    password = password.encode() if isinstance(password, str) else password
    salt_bytes = salt_value.encode() if isinstance(salt_value, str) else salt_value
    return hashlib.pbkdf2_hmac(
        digest().name, password, salt_bytes, iterations, dklen,
    )


def make_password(
    password: Optional[str],
    salt_value: Optional[str] = None,
    iterations: Optional[int] = None,
) -> str:
    """Hash ``password``; ``None`` yields an unusable placeholder."""
    if password is None:
        return '%s%s' % (
            UNUSABLE_PASSWORD_PREFIX,
            get_random_string(UNUSABLE_PASSWORD_SUFFIX_LENGTH),
        )
    if salt_value is None:
        salt_value = salt()
    if iterations is None:
        iterations = ITERATIONS
    if '$' in salt_value:
        raise ValueError('salt must not contain $')
    digest = pbkdf2(password, salt_value, iterations)
    encoded = base64.b64encode(digest).decode('ascii').strip()
    return '%s$%d$%s$%s' % (ALGORITHM, iterations, salt_value, encoded)


def is_password_usable(encoded: Optional[str]) -> bool:
    return encoded is None or not encoded.startswith(UNUSABLE_PASSWORD_PREFIX)


def check_password(
    password: Optional[str],
    encoded: Optional[str],
    setter: Optional[Callable[[str], Any]] = None,
) -> bool:
    """Constant-time verification of ``password`` against ``encoded``."""
    if password is None or not encoded or not is_password_usable(encoded):
        return False
    try:
        algorithm, iterations, salt_value, _digest = encoded.split('$', 3)
    except ValueError:
        return False
    if algorithm != ALGORITHM:
        return False
    try:
        iterations = int(iterations)
    except (TypeError, ValueError):
        return False
    candidate = make_password(password, salt_value, iterations)
    correct = hmac.compare_digest(candidate.encode(), encoded.encode())
    if correct and setter and iterations != ITERATIONS:
        setter(password)
    return correct


def constant_time_compare(val1, val2) -> bool:
    if isinstance(val1, str):
        val1 = val1.encode()
    if isinstance(val2, str):
        val2 = val2.encode()
    return hmac.compare_digest(val1, val2)


def salted_hmac(key_salt, value, secret, algorithm: str = 'sha256'):
    hasher = getattr(hashlib, algorithm)
    key_salt = key_salt.encode() if isinstance(key_salt, str) else key_salt
    secret = secret.encode() if isinstance(secret, str) else secret
    key = hasher(key_salt + secret).digest()
    value = value.encode() if isinstance(value, str) else value
    return hmac.new(key, msg=value, digestmod=hasher)


# ---------------------------------------------------------------------------
# Auth tokens
# ---------------------------------------------------------------------------

def generate_token() -> str:
    """A 40 character hex auth token, matching the stored column width."""
    return secrets.token_hex(20)


# ---------------------------------------------------------------------------
# uidb64 helpers
# ---------------------------------------------------------------------------

def urlsafe_base64_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode('ascii').rstrip('=')


def urlsafe_base64_decode(value: str) -> bytes:
    value = str(value)
    padding = '=' * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def force_bytes(value) -> bytes:
    if isinstance(value, bytes):
        return value
    return str(value).encode('utf-8')


# ---------------------------------------------------------------------------
# Password reset tokens
# ---------------------------------------------------------------------------

_BASE36 = '0123456789abcdefghijklmnopqrstuvwxyz'


def int_to_base36(value: int) -> str:
    if value < 0:
        raise ValueError('Negative base36 conversion input.')
    if value < 36:
        return _BASE36[value]
    out = ''
    while value:
        value, index = divmod(value, 36)
        out = _BASE36[index] + out
    return out


def base36_to_int(value: str) -> int:
    if len(value) > 13:
        raise ValueError('Base36 input too large')
    return int(value, 36)


class PasswordResetTokenGenerator:
    """Signed, time limited, single-use-by-password-change reset tokens.

    The hash mixes the user primary key, the current password hash, the
    last login stamp and the timestamp, so changing the password or
    logging in invalidates any outstanding link -- the same invalidation
    rules the baseline had.
    """

    key_salt = 'app.security.PasswordResetTokenGenerator'
    algorithm = 'sha256'

    def __init__(self, secret: Optional[str] = None):
        from app import settings
        self.secret = secret or settings.SECRET_KEY

    def make_token(self, user) -> str:
        return self._make_token_with_timestamp(user, self._num_seconds(self._now()))

    def check_token(self, user, token: Optional[str]) -> bool:
        if not (user and token):
            return False
        try:
            ts_b36, _hash = token.split('-')
        except ValueError:
            return False
        try:
            timestamp = base36_to_int(ts_b36)
        except ValueError:
            return False
        expected = self._make_token_with_timestamp(user, timestamp)
        if not constant_time_compare(expected, token):
            return False
        if (self._num_seconds(self._now()) - timestamp) > PASSWORD_RESET_TIMEOUT:
            return False
        return True

    def _make_token_with_timestamp(self, user, timestamp: int) -> str:
        ts_b36 = int_to_base36(timestamp)
        hash_string = salted_hmac(
            self.key_salt,
            self._make_hash_value(user, timestamp),
            secret=self.secret,
            algorithm=self.algorithm,
        ).hexdigest()[::2]
        return '%s-%s' % (ts_b36, hash_string)

    def _make_hash_value(self, user, timestamp: int) -> str:
        login_timestamp = getattr(user, 'last_login', None)
        if login_timestamp is not None:
            login_timestamp = login_timestamp.replace(microsecond=0, tzinfo=None)
        return '%s%s%s%s' % (
            user.pk, user.password, login_timestamp, timestamp,
        )

    def _num_seconds(self, dt: datetime.datetime) -> int:
        return int((dt - datetime.datetime(2001, 1, 1)).total_seconds())

    def _now(self) -> datetime.datetime:
        return datetime.datetime.now()


default_token_generator = PasswordResetTokenGenerator()
