"""Password strength validators.

These exist because ``settings.AUTH_PASSWORD_VALIDATORS`` names them.
Nothing calls them: the baseline configured the same four validators and
never wired them into the create or update paths either, so a five
character password is accepted on both stacks.  Preserved on purpose --
see the shortfall list in ``PORT_PLAN.md``.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from app.i18n import gettext as _


class ValidationError(Exception):
    """Raised by a validator when a password is rejected."""

    def __init__(self, message: str, code: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.code = code


class UserAttributeSimilarityValidator:
    """Reject passwords that look like the user's own attributes."""

    DEFAULT_USER_ATTRIBUTES = ('username', 'name', 'surname', 'email')

    def __init__(self, user_attributes=DEFAULT_USER_ATTRIBUTES, max_similarity: float = 0.7):
        self.user_attributes = user_attributes
        self.max_similarity = max_similarity

    def validate(self, password: str, user: Any = None) -> None:
        if not user:
            return
        lowered = password.lower()
        for attribute_name in self.user_attributes:
            value = getattr(user, attribute_name, None)
            if not value or not isinstance(value, str):
                continue
            for part in re.split(r'\W+', value) + [value]:
                if part and part.lower() == lowered:
                    raise ValidationError(
                        _('The password is too similar to the %s.') % attribute_name,
                        code='password_too_similar',
                    )


class MinimumLengthValidator:
    """Reject passwords shorter than ``min_length``."""

    def __init__(self, min_length: int = 8):
        self.min_length = min_length

    def validate(self, password: str, user: Any = None) -> None:
        if len(password) < self.min_length:
            raise ValidationError(
                _('This password is too short.'),
                code='password_too_short',
            )


class CommonPasswordValidator:
    """Reject a small set of obviously common passwords."""

    DEFAULT_PASSWORD_LIST = frozenset({
        'password', '123456', '12345678', '123456789', 'qwerty',
        'abc123', 'password1', '1234567', 'iloveyou', 'admin',
    })

    def __init__(self, password_list=DEFAULT_PASSWORD_LIST):
        self.passwords = password_list

    def validate(self, password: str, user: Any = None) -> None:
        if password.lower().strip() in self.passwords:
            raise ValidationError(
                _('This password is too common.'),
                code='password_too_common',
            )


class NumericPasswordValidator:
    """Reject passwords made up entirely of digits."""

    def validate(self, password: str, user: Any = None) -> None:
        if password.isdigit():
            raise ValidationError(
                _('This password is entirely numeric.'),
                code='password_entirely_numeric',
            )
