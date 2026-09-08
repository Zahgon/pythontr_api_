"""The middleware stack.

Order is load-bearing.  Outermost first:

``Security`` → ``Session`` → ``Common`` → ``CsrfView`` → ``Authentication``
→ ``Message`` → ``XFrameOptions`` → ``Locale``

Two consequences of that order show up on the wire and both are
reproduced here:

*   ``Common`` answers the missing-trailing-slash ``301`` itself, before
    the request ever reaches ``XFrameOptions`` or ``Locale``.  So that
    redirect carries the three security headers and nothing else -- no
    ``X-Frame-Options``, no ``Content-Language``, no ``Vary``.

*   ``Locale`` is innermost, so ``Vary: Accept-Language`` is appended to
    whatever ``Vary`` the view already set.  View responses carry
    ``Vary: Accept, Accept-Language``; the framework's own error pages,
    which no view produced, carry only ``Vary: Accept-Language``.
"""

from __future__ import annotations

import traceback
from typing import Awaitable, Callable, Optional, Sequence
from urllib.parse import quote

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Match
from starlette.types import ASGIApp, Receive, Scope, Send

from app import settings
from app.urls import split_format_suffix
from app.wire import ApiError, bad_request_page, error_response, get_allow
from app.wire import not_found_page, server_error_page

Handler = Callable[[Request], Awaitable[Response]]


class FormatSuffixMiddleware:
    """Resolve a ``.json`` / ``.api`` URL suffix before anything else runs.

    The baseline's routers registered a suffixed twin for every route they
    generated, so ``/api/recipe/categories/5.json`` reached the same view as
    ``/api/recipe/categories/5/`` with the renderer pinned.  Rewriting the
    path here and recording the format on the scope reproduces that;
    :func:`app.deps._negotiate` reads it back.

    It has to sit outside ``Common``.  The baseline resolved suffixes inside
    the URLconf, and its ``APPEND_SLASH`` check consulted that same URLconf,
    so a suffixed path was never a candidate for the trailing-slash
    redirect.  Seeing the rewritten path gives ``Common`` the same answer.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send,
    ) -> None:
        if scope.get('type') == 'http':
            path, suffix = split_format_suffix(scope.get('path', ''))
            if suffix is not None:
                scope['format_suffix'] = suffix
                scope['path'] = path
                if 'raw_path' in scope:
                    scope['raw_path'] = quote(path).encode('ascii')
        await self.app(scope, receive, send)


def _append_vary(response: Response, value: str) -> None:
    existing = response.headers.get('Vary')
    if not existing:
        response.headers['Vary'] = value
        return
    members = [part.strip() for part in existing.split(',') if part.strip()]
    if value.lower() not in [member.lower() for member in members]:
        members.append(value)
    response.headers['Vary'] = ', '.join(members)


class SecurityMiddleware(BaseHTTPMiddleware):
    """Outermost.  Stamps the three headers every response carries."""

    async def dispatch(self, request: Request, call_next: Handler) -> Response:
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Cross-Origin-Opener-Policy'] = 'same-origin'
        return response


class SessionMiddleware(BaseHTTPMiddleware):
    """Attaches an empty session mapping.

    The baseline installed a session backend for the admin site; the API
    never reads it and never sets a session cookie, so nothing is
    persisted here either.
    """

    async def dispatch(self, request: Request, call_next: Handler) -> Response:
        request.scope.setdefault('session', {})
        return await call_next(request)


def _resolves(request: Request, path: str) -> bool:
    """Would ``path`` match a mounted route?"""
    router = request.scope.get('app')
    if router is None:
        return False
    scope = dict(request.scope)
    scope['path'] = path
    scope['raw_path'] = path.encode('utf-8')
    for route in router.routes:
        match, _child = route.matches(scope)
        if match is not Match.NONE:
            return True
    return False


class DisallowedHost(Exception):
    pass


def _host_is_allowed(host: str, patterns: Sequence[str]) -> bool:
    host = host.lower().rstrip('.')
    if host.startswith('[') and host.endswith(']'):
        bare = host
    else:
        bare = host.rsplit(':', 1)[0] if host.count(':') == 1 else host
    for pattern in patterns:
        pattern = pattern.lower().strip()
        if not pattern:
            continue
        if pattern == '*':
            return True
        if pattern.startswith('.'):
            if bare.endswith(pattern) or bare == pattern[1:]:
                return True
        elif bare == pattern:
            return True
    return False


class CommonMiddleware(BaseHTTPMiddleware):
    """``ALLOWED_HOSTS`` validation, then the ``APPEND_SLASH`` redirect.

    Both are answered without calling the inner layers, so they carry the
    outer security headers and nothing from ``XFrameOptions`` or ``Locale``.
    """

    async def dispatch(self, request: Request, call_next: Handler) -> Response:
        host = request.headers.get('host', '')
        patterns = getattr(settings, 'ALLOWED_HOSTS', None) or []
        if patterns and not _host_is_allowed(host, patterns):
            exc = DisallowedHost(
                "Invalid HTTP_HOST header: %r. You may need to add %r to "
                'ALLOWED_HOSTS.' % (host, host.rsplit(':', 1)[0]))
            return Response(
                content=bad_request_page(
                    request, exc, ''.join(traceback.format_exception_only(
                        type(exc), exc))),
                status_code=400,
                media_type='text/html; charset=utf-8',
            )
        path = request.scope.get('path', '')
        if (getattr(settings, 'APPEND_SLASH', False)
                and path
                and not path.endswith('/')
                and not _resolves(request, path)
                and _resolves(request, path + '/')):
            location = path + '/'
            query = request.scope.get('query_string', b'')
            if query:
                location = '%s?%s' % (location, query.decode('latin-1'))
            return Response(
                status_code=301,
                headers={'Location': location},
                media_type='text/html; charset=utf-8',
            )
        return await call_next(request)


class CsrfViewMiddleware(BaseHTTPMiddleware):
    """Token-authenticated requests are exempt, so this only passes through.

    The baseline installed the same protection and the API views were
    likewise exempt from it; no probe in the matrix sees a CSRF failure.
    """

    async def dispatch(self, request: Request, call_next: Handler) -> Response:
        return await call_next(request)


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """Seeds the anonymous user.

    Real authentication happens per route through ``app.deps.access`` so
    that each route keeps its own authenticator ordering; this layer only
    guarantees ``request.scope['user']`` exists for code that reads it
    before a dependency has run.
    """

    async def dispatch(self, request: Request, call_next: Handler) -> Response:
        from core.models import AnonymousUser
        request.scope.setdefault('user', AnonymousUser())
        return await call_next(request)


class MessageMiddleware(BaseHTTPMiddleware):
    """Flash-message storage for the admin site."""

    async def dispatch(self, request: Request, call_next: Handler) -> Response:
        request.scope.setdefault('messages', [])
        return await call_next(request)


class XFrameOptionsMiddleware(BaseHTTPMiddleware):
    """Adds ``X-Frame-Options``.

    Inside ``Common``, so the trailing-slash redirect never reaches it.
    """

    async def dispatch(self, request: Request, call_next: Handler) -> Response:
        response = await call_next(request)
        response.headers.setdefault(
            'X-Frame-Options', getattr(settings, 'X_FRAME_OPTIONS', 'DENY'))
        return response


class LocaleMiddleware(BaseHTTPMiddleware):
    """Innermost.  Adds ``Content-Language`` and varies on it."""

    async def dispatch(self, request: Request, call_next: Handler) -> Response:
        response = await call_next(request)
        response.headers.setdefault(
            'Content-Language', getattr(settings, 'LANGUAGE_CODE', 'tr'))
        _append_vary(response, 'Accept-Language')
        return response


class ExceptionMiddleware(BaseHTTPMiddleware):
    """Turns route failures into the bodies the baseline produced.

    Sits just inside ``Locale`` so its output still picks up the locale
    and clickjacking headers.  Anything that is not an ``ApiError``
    becomes the framework's debug ``500`` page -- which is what the
    baseline does for the handful of preserved crashes.
    """

    async def dispatch(self, request: Request, call_next: Handler) -> Response:
        try:
            return await call_next(request)
        except ApiError as exc:
            return error_response(request, exc)
        except Exception as exc:  # noqa: BLE001 - deliberate catch-all
            if request.scope.get('reraise_exceptions'):
                raise
            request.scope.pop('allow_methods', None)
            body = server_error_page(
                request, exc, traceback.format_exc())
            return Response(
                content=body,
                status_code=500,
                media_type='text/html; charset=utf-8',
            )


class NotFoundMiddleware(BaseHTTPMiddleware):
    """Replaces the bare ``404`` body with the framework's debug page."""

    async def dispatch(self, request: Request, call_next: Handler) -> Response:
        response = await call_next(request)
        if response.status_code == 404 and get_allow(request) is None:
            return Response(
                content=not_found_page(request),
                status_code=404,
                media_type='text/html; charset=utf-8',
            )
        return response


def stamp_allow(request: Request, response: Response) -> Optional[str]:
    """Copy the route's allowed methods onto the response."""
    allow = get_allow(request)
    if allow:
        response.headers['Allow'] = allow
    return allow


class AllowHeaderMiddleware(BaseHTTPMiddleware):
    """Stamps ``Allow`` on every response a route produced.

    The baseline emits it on successes, on ``401``/``403`` rejections and
    on ``405``, not only on method-not-allowed.
    """

    async def dispatch(self, request: Request, call_next: Handler) -> Response:
        response = await call_next(request)
        stamp_allow(request, response)
        return response
