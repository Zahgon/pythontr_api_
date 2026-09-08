"""Pydantic input models and response builders for the public user endpoints.

Key order in every ``serialize_*`` return value is part of the published wire
contract, so the payloads are built as explicit dicts rather than dumped from a
response model.
"""

from __future__ import annotations

import re
import sys
from typing import Any, ClassVar, Dict, FrozenSet, List, Optional

import requests
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_core import PydanticCustomError

from app import settings
from app.i18n import gettext as _
from app.wire import ValidationFailed

CAPTCHA_REQUIRED = not settings.DEBUG and 'test' not in sys.argv

#: The captcha fork only declares the field when it is required, and a field
#: the baseline never declares cannot reject anything, so an explicit null is
#: ignored exactly while the fork is off.
_CAPTCHA_NULLABLE = () if CAPTCHA_REQUIRED else ('captcha',)


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_email(value: Optional[str]) -> Optional[str]:
    """Reject malformed addresses with the framework's own message."""
    if value is None:
        return value
    if not _EMAIL_RE.match(value):
        raise PydanticCustomError('email_format', 'invalid email address')
    return value


def verify_captcha(value: str) -> str:
    """Check a reCAPTCHA response against the hardcoded verification URL."""
    response = requests.post(
        settings.RECAPTCHA_URL,
        data={'secret': settings.RECAPTCHA_SECRET_KEY, 'response': value},
    )
    result = response.json()
    if not result.get('success'):
        raise ValidationFailed({'captcha': [_('recaptcha_verification_failed')]})
    return value


class UserInput(BaseModel):
    """Write model for ``POST /api/user/create/``."""

    model_config = ConfigDict(extra='ignore')
    nullable_fields: ClassVar[FrozenSet[str]] = frozenset(
        ('image',) + _CAPTCHA_NULLABLE)

    email: str = Field(min_length=1)
    password: str = Field(min_length=5)
    confirm_password: Optional[str] = None
    username: str = Field(min_length=1)
    name: Optional[str] = None
    surname: Optional[str] = None
    image: Optional[str] = None
    about_me: Optional[str] = None
    linkedin: Optional[str] = None
    github: Optional[str] = None
    is_notification_email: Optional[bool] = None
    is_staff: Optional[bool] = None
    current_password: Optional[str] = None
    captcha: Optional[str] = None

    _check_email = field_validator('email')(_validate_email)


USER_INPUT_ORDER = (
    'email',
    'password',
    'confirm_password',
    'username',
    'name',
    'surname',
    'image',
    'about_me',
    'linkedin',
    'github',
    'is_notification_email',
    'is_staff',
    'current_password',
    'captcha',
)


class UserUpdateInput(BaseModel):
    """Write model for ``PUT``/``PATCH /api/user/me/``.

    Every field is optional because the baseline validates the password trio in
    ``validate()`` rather than at field level.
    """

    model_config = ConfigDict(extra='ignore')
    nullable_fields: ClassVar[FrozenSet[str]] = frozenset(
        ('image',) + _CAPTCHA_NULLABLE)

    email: Optional[str] = None
    password: Optional[str] = Field(default=None, min_length=5)
    confirm_password: Optional[str] = None
    username: Optional[str] = None
    name: Optional[str] = None
    surname: Optional[str] = None
    image: Optional[str] = None
    about_me: Optional[str] = None
    linkedin: Optional[str] = None
    github: Optional[str] = None
    is_notification_email: Optional[bool] = None
    is_staff: Optional[bool] = None
    current_password: Optional[str] = None
    captcha: Optional[str] = None

    _check_email = field_validator('email')(_validate_email)


USER_UPDATE_INPUT_ORDER = USER_INPUT_ORDER


class AuthTokenInput(BaseModel):
    """Write model for ``POST /api/user/token/``."""

    model_config = ConfigDict(extra='ignore')
    nullable_fields: ClassVar[FrozenSet[str]] = frozenset(
        _CAPTCHA_NULLABLE)

    email: str = Field(min_length=1)
    password: str = Field(min_length=1)
    captcha: Optional[str] = None


AUTH_TOKEN_INPUT_ORDER = ('email', 'password', 'captcha')


class ResendActivationInput(BaseModel):
    model_config = ConfigDict(extra='ignore')
    nullable_fields: ClassVar[FrozenSet[str]] = frozenset(
        _CAPTCHA_NULLABLE)

    email: str = Field(min_length=1)
    captcha: Optional[str] = None

    _check_email = field_validator('email')(_validate_email)


RESEND_ACTIVATION_INPUT_ORDER = ('email', 'captcha')


class PasswordResetInput(BaseModel):
    model_config = ConfigDict(extra='ignore')
    nullable_fields: ClassVar[FrozenSet[str]] = frozenset(
        _CAPTCHA_NULLABLE)

    email: str = Field(min_length=1)
    captcha: Optional[str] = None

    _check_email = field_validator('email')(_validate_email)


PASSWORD_RESET_INPUT_ORDER = ('email', 'captcha')


class PasswordResetConfirmInput(BaseModel):
    model_config = ConfigDict(extra='ignore')
    nullable_fields: ClassVar[FrozenSet[str]] = frozenset(
        _CAPTCHA_NULLABLE)

    password: str = Field(min_length=8)
    confirm_password: str = Field(min_length=1)
    token: str = Field(min_length=1)
    uidb64: str = Field(min_length=1)
    captcha: Optional[str] = None


PASSWORD_RESET_CONFIRM_INPUT_ORDER = (
    'password',
    'confirm_password',
    'token',
    'uidb64',
    'captcha',
)


WRITABLE_FIELDS = (
    'email',
    'username',
    'name',
    'surname',
    'image',
    'about_me',
    'linkedin',
    'github',
    'is_notification_email',
)


def serialize_user(obj: Any) -> Dict[str, Any]:
    """Render a user exactly as ``UserSerializer`` does.

    ``id``, ``password`` and the timestamps are deliberately absent: the
    baseline's field list omits them.
    """
    return {
        'email': obj.email,
        'username': obj.username,
        'name': obj.name,
        'surname': obj.surname,
        'image': obj.image or None,
        'about_me': obj.about_me,
        'linkedin': obj.linkedin,
        'github': obj.github,
        'is_notification_email': obj.is_notification_email,
        'image_url': obj.image_url,
        'slug': obj.slug,
        'is_staff': obj.is_staff,
    }


def captcha_errors(data: Dict[str, Any]) -> Optional[Dict[str, List[str]]]:
    """Return the missing-captcha error body when the captcha fork is active."""
    if not CAPTCHA_REQUIRED:
        return None
    if 'captcha' not in data:
        return {'captcha': [_('This field is required.')]}
    if data['captcha'] is None:
        return {'captcha': [_('This field may not be null.')]}
    if not data['captcha']:
        return {'captcha': [_('This field may not be blank.')]}
    verify_captcha(data['captcha'])
    return None
