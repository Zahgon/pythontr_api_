"""Request-scoped dependencies.

Everything a route needs before its body runs -- a database session, the
authenticated user, and the permission verdict -- is expressed here as a
``Depends`` callable.  Routes declare what they need; nothing is
inherited from a base class.

Two ordering rules from the baseline are reproduced deliberately:

*   Authentication runs before permissions, and both run before method
    resolution.  ``DELETE`` on a read-only collection therefore answers
    ``401`` to an anonymous caller, not ``405``.  The routers arrange
    this by registering a catch-all handler for the complement of the
    allowed methods that depends on the same permission callable.

*   The ``WWW-Authenticate`` header -- and with it the 401-vs-403 split
    -- comes from the *first* authenticator the route lists, whichever
    one actually rejected the request.
"""

from __future__ import annotations

from typing import Callable, List, Optional, Sequence, Tuple

from fastapi import Depends
from sqlalchemy.orm import Session
from starlette.requests import Request

from app import db as _db
from app.authentication import CookieTokenAuthentication, TokenAuthentication
from app.browsable import wants_html
from app.i18n import gettext as _
from app.wire import ApiError, NotAcceptable, NotAuthenticated, NotFound
from app.wire import PermissionDenied, set_allow
from core.models import AnonymousUser, User

SAFE_METHODS = ('GET', 'HEAD', 'OPTIONS')

#: The two authenticator orderings the baseline uses.  ``TOKEN_FIRST`` is
#: what the views name explicitly; ``COOKIE_FIRST`` is the settings
#: default the admin routes fall back to, and it is why those answer 403.
TOKEN_FIRST = (TokenAuthentication(), CookieTokenAuthentication())
COOKIE_FIRST = (CookieTokenAuthentication(), TokenAuthentication())


def get_db() -> Session:
    """Yield the request-scoped session, committing on a clean return.

    The session must be released before the response leaves, otherwise the
    pooled connection stays ``idle in transaction`` and the harness's
    snapshot restore blocks on the table locks it still holds.

    When the test harness has bound an external connection the commit is
    skipped: that connection lives inside a transaction the fixture rolls
    back itself.
    """
    session = _db.get_session()
    shared = _db.get_shared_connection()
    try:
        yield session
        if shared is None:
            session.commit()
        else:
            session.flush()
    except Exception:
        session.rollback()
        raise
    finally:
        if shared is None:
            _db.remove_session()


def _authenticate(
    request: Request,
    session: Session,
    authenticators: Sequence[object],
) -> Tuple[object, Optional[str]]:
    """Run the authenticators in order and return ``(user, token)``.

    Returns ``AnonymousUser`` when no authenticator offered credentials.
    Any rejection is re-raised carrying the *first* authenticator's
    scheme, matching the baseline's header handling.

    ``forced_user`` short-circuits the whole exchange.  It is placed in the
    scope by :meth:`app.testing.APIClient.force_authenticate` and carries
    the caller's own object, so a permission predicate observes attribute
    changes the caller never persisted.
    """
    forced = request.scope.get('forced_user')
    if forced is not None:
        forced_token = request.scope.get('forced_token')
        request.scope['user'] = forced
        request.scope['auth'] = forced_token
        return forced, forced_token

    scheme = authenticators[0].authenticate_header(request)
    for authenticator in authenticators:
        try:
            result = authenticator.authenticate(request, session)
        except ApiError as exc:
            exc.headers = dict(exc.headers or {})
            exc.headers.pop('WWW-Authenticate', None)
            if scheme:
                exc.status_code = 401
                exc.headers['WWW-Authenticate'] = scheme
            else:
                exc.status_code = 403
            raise
        if result is not None:
            user, token = result
            request.scope['user'] = user
            request.scope['auth'] = token
            return user, token
    anonymous = AnonymousUser()
    request.scope['user'] = anonymous
    request.scope['auth'] = None
    return anonymous, None


def _denied(request: Request, user: object, scheme: Optional[str]) -> ApiError:
    """Pick the rejection an unmet permission produces."""
    if getattr(user, 'is_authenticated', False):
        return PermissionDenied()
    return NotAuthenticated(auth_header=scheme)


# --------------------------------------------------------------------------
# Permission predicates.  Each answers "may this request proceed?".
# --------------------------------------------------------------------------

def allow_any(request: Request, user: object) -> bool:
    return True


def is_authenticated(request: Request, user: object) -> bool:
    return bool(getattr(user, 'is_authenticated', False))


def is_admin_user(request: Request, user: object) -> bool:
    return bool(getattr(user, 'is_authenticated', False)
                and getattr(user, 'is_staff', False))


def is_authenticated_or_read_only(request: Request, user: object) -> bool:
    if request.method in SAFE_METHODS:
        return True
    return is_authenticated(request, user)


class Access:
    """What a route body receives: the session, the user, the token."""

    __slots__ = ('session', 'user', 'token', 'request')

    def __init__(
        self,
        session: Session,
        user: object,
        token: Optional[str],
        request: Request,
    ) -> None:
        self.session = session
        self.user = user
        self.token = token
        self.request = request

    @property
    def is_staff(self) -> bool:
        return bool(getattr(self.user, 'is_staff', False))

    @property
    def is_authenticated(self) -> bool:
        return bool(getattr(self.user, 'is_authenticated', False))


RENDERER_MEDIA_TYPES = ('application/json', 'text/html')

#: The ``format`` query parameter values the baseline understood, each
#: mapped to the renderer it selects and the media type that renderer
#: emits.  The comparison against this table is exact: upstream matched a
#: renderer by its ``format`` attribute, so ``?format=JSON`` selected
#: nothing and answered 404, and so does it here.
RENDERER_FORMATS = {
    'json': ('json', 'application/json'),
    'api': ('html', 'text/html'),
}


def _acceptable(header: str, offered: Sequence[str]) -> bool:
    """Report whether ``header`` admits any of the ``offered`` media types.

    A missing or blank header is the same as ``*/*``, which admits
    everything -- that is what the baseline did with a request that named
    no preference at all.
    """
    if not header.strip():
        return True
    for part in header.split(','):
        media_range = part.split(';')[0].strip().lower()
        if not media_range:
            continue
        if media_range == '*/*':
            return True
        main, _sep, sub = media_range.partition('/')
        for candidate in offered:
            candidate_main, candidate_sub = candidate.split('/')
            if main == candidate_main and sub in ('*', candidate_sub):
                return True
    return False


def _requested_format(request: Request) -> str:
    """Return the requested format, or the empty string.

    A ``.json`` / ``.api`` URL suffix outranks the query parameter, which is
    the order the baseline resolved them in, so
    ``/api/recipe/categories/5.json?format=api`` answers JSON.

    Repeating the query parameter is not an error; the baseline read it out
    of a multi-valued mapping whose accessor returns the last value, so the
    last one wins here too.  An empty value is no value: ``?format=`` leaves
    the choice to the ``Accept`` header.
    """
    suffix = request.scope.get('format_suffix')
    if suffix:
        return suffix
    values = request.query_params.getlist('format')
    return values[-1] if values else ''


def _negotiate(request: Request) -> None:
    """Select the renderer for ``?format=`` and ``Accept``, or reject.

    The ``format`` query parameter is resolved first, and resolving it can
    end the request two ways.  A value naming no renderer answers 404 --
    before the ``Accept`` header is consulted and, because this runs ahead
    of authentication, before the caller is identified, so an unknown
    format on a protected route answers 404 rather than 401.  A value
    naming one narrows the offered representations to that single one, so
    an ``Accept`` header excluding it can no longer be satisfied and
    answers 406.  Both orderings are the baseline's.

    Without the parameter the choice belongs to ``Accept`` alone, and an
    unacceptable media type answers 406 even to an anonymous caller on a
    protected route.  The chosen renderer is recorded on the scope;
    ``app.wire`` reads it when it builds the response.
    """
    header = request.headers.get('accept', '')
    request.scope['renderer'] = 'json'
    requested = _requested_format(request)
    if requested:
        selected = RENDERER_FORMATS.get(requested)
        if selected is None:
            raise NotFound()
        renderer, media_type = selected
        if not _acceptable(header, (media_type,)):
            raise NotAcceptable()
        request.scope['renderer'] = renderer
        return
    if not _acceptable(header, RENDERER_MEDIA_TYPES):
        raise NotAcceptable()
    if wants_html(header):
        request.scope['renderer'] = 'html'


def access(
    permission: Callable[[Request, object], bool] = allow_any,
    authenticators: Sequence[object] = TOKEN_FIRST,
    allow: Optional[Sequence[str]] = None,
) -> Callable[..., Access]:
    """Build the dependency a route declares.

    ``permission`` is one of the predicates above.  ``authenticators``
    fixes the 401-vs-403 behaviour for the route.  ``allow`` is the set
    of methods the *path* serves; it is recorded on the request before
    anything else runs so the ``Allow`` header survives onto the 401 or
    403 this dependency may raise.
    """

    def dependency(
        request: Request,
        session: Session = Depends(get_db),
    ) -> Access:
        if allow is not None:
            set_allow(request, allow)
        _negotiate(request)
        user, token = _authenticate(request, session, authenticators)
        scheme = authenticators[0].authenticate_header(request)
        if not permission(request, user):
            raise _denied(request, user, scheme)
        return Access(session, user, token, request)

    return dependency


def check_object_permission(
    ctx: Access,
    obj: object,
    admin_override: bool = False,
) -> None:
    """Owner check applied to a single row.

    Safe methods always pass.  A row without a ``user`` attribute never
    passes.  ``admin_override`` mirrors ``IsAuthenticatedAndOwnerOrAdmin``.
    """
    if ctx.request.method in SAFE_METHODS:
        return
    if admin_override and ctx.is_staff:
        return
    owner = getattr(obj, 'user', None)
    if owner is not None and getattr(owner, 'id', None) == getattr(
            ctx.user, 'id', object()):
        return
    raise PermissionDenied()


def resolve_users(session: Session, ids: List[int]) -> List[User]:
    """Small helper the admin routes share."""
    if not ids:
        return []
    return list(session.query(User).filter(User.id.in_(ids)).all())
