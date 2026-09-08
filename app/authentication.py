"""Request authenticators.

Two of them, in the order ``settings.API['DEFAULT_AUTHENTICATION_CLASSES']``
lists them.  Which one comes first on a given view decides more than who
gets authenticated -- it also decides whether an unauthenticated request
is answered ``401`` or ``403``, because the status is taken from the
first authenticator's ``authenticate_header``.

``CookieTokenAuthentication`` reads the token out of a ``session`` cookie.
It has never authenticated anybody: it looks the token up on the
framework's built-in user table while the project's user model is
``core.User``, so the relation it filters on does not exist there.  The
lookup below reproduces that -- ``_builtin_user_with_token`` always
misses -- and the callers swallow the failure exactly as the baseline
did.  See PORT_PLAN.md preserved defect 1.
"""

from __future__ import annotations

import json
from typing import Optional, Tuple
from urllib.parse import unquote

from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.i18n import gettext as _
from app.wire import AuthenticationFailed
from core.models import Token, User


class TokenAuthentication:
    """``Authorization: Token <key>``."""

    keyword = 'Token'

    def authenticate_header(self, request: Request) -> str:
        return self.keyword

    def authenticate(
        self, request: Request, session: Session
    ) -> Optional[Tuple[User, str]]:
        header = request.headers.get('authorization', '')
        parts = header.split()
        if not parts or parts[0].lower() != self.keyword.lower():
            return None
        if len(parts) == 1:
            raise AuthenticationFailed(
                _('Invalid token header. No credentials provided.'))
        if len(parts) > 2:
            raise AuthenticationFailed(
                _('Invalid token header. '
                  'Token string should not contain spaces.'))
        try:
            key = parts[1].decode() if isinstance(parts[1], bytes) else parts[1]
        except UnicodeError:
            raise AuthenticationFailed(
                _('Invalid token header. '
                  'Token string should not contain invalid characters.'))
        return self.authenticate_credentials(key, session)

    def authenticate_credentials(
        self, key: str, session: Session
    ) -> Tuple[User, str]:
        token = session.scalars(
            select(Token).where(Token.key == key)).first()
        if token is None:
            raise AuthenticationFailed(_('Invalid token.'))
        user = token.user
        if user is None or not user.is_active:
            raise AuthenticationFailed(_('User inactive or deleted.'))
        return (user, token.key)


def _builtin_user_with_token(session: Session, token: str) -> Optional[User]:
    """Resolve ``token`` against the framework's built-in user table.

    The built-in table carries no relation to the project's token model,
    so this never resolves anybody.  Kept as a named function so the
    defect is legible rather than looking like a typo.
    """
    return None


class CookieTokenAuthentication:
    """Token carried in a JSON ``session`` cookie.

    Returns ``None`` when the cookie is absent or is not the JSON
    document it expects -- which is what the probe matrix observes, since
    a bare token in the cookie fails to parse and the request falls
    through as anonymous.
    """

    def authenticate_header(self, request: Request) -> Optional[str]:
        return None

    def authenticate(
        self, request: Request, session: Session
    ) -> Optional[Tuple[User, str]]:
        raw = request.cookies.get('session')
        if not raw:
            return None
        try:
            token = json.loads(unquote(raw)).get('token')
        except (json.JSONDecodeError, AttributeError, ValueError):
            return None
        if not token:
            return None
        if not isinstance(token, str):
            raise AuthenticationFailed('Geçersiz token formatı.')
        user = _builtin_user_with_token(session, token)
        if user is None:
            return None
        if not user.is_active:
            raise AuthenticationFailed('Kullanıcı hesabı aktif değil.')
        return (user, token)
