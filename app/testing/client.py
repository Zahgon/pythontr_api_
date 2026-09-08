"""The in-process HTTP client the suite drives the application with.

Requests go through every middleware layer, every dependency and every
router, and come back as real responses; nothing is stubbed.  Three
behaviours a bare HTTP client cannot provide are added here.

**Identity-preserving authentication.**  ``force_authenticate`` does not
mint a token and it does not reload the row.  It puts the caller's own
object into the ASGI scope under ``forced_user``, where
``app.deps._authenticate`` picks it up, so a test can flip
``user.is_staff`` without saving and the permission predicate observes the
change -- it is looking at the very same object.

**Exceptions reach the test.**  ``app.middleware.ExceptionMiddleware``
re-raises instead of rendering a 500 page whenever
``scope['reraise_exceptions']`` is set, and this client always sets it.

**Form-encoded writes by default.**  ``POST``/``PUT``/``PATCH`` bodies are
``multipart/form-data`` unless ``format='json'`` is asked for.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import httpx
from starlette.testclient import TestClient

from app.testing.encoding import (
    JSON_CONTENT,
    MULTIPART_CONTENT,
    _encode_json,
    encode_multipart,
)
from app.testing.response import Response

_BODY_METHODS = frozenset({'POST', 'PUT', 'PATCH'})
_QUERY_METHODS = frozenset({'GET', 'HEAD', 'OPTIONS'})


class _ScopeInjector:
    """ASGI wrapper seeding the scope entries the harness relies on.

    It sits outside every middleware layer, so the values are present
    before anything reads them -- including ``ExceptionMiddleware``, which
    consults ``reraise_exceptions`` only once a route has already failed.
    """

    def __init__(self, application: Any, client: 'APIClient') -> None:
        self._application = application
        self._client = client

    async def __call__(self, scope: Dict[str, Any], receive: Any,
                       send: Any) -> None:
        if scope.get('type') == 'http':
            scope['reraise_exceptions'] = True
            user = self._client.forced_user
            if user is not None:
                scope['forced_user'] = user
                scope['forced_token'] = self._client.forced_token
        await self._application(scope, receive, send)


def _default_application() -> Any:
    """The ASGI object the suite drives.

    ``app.main.application`` is the framework instance itself.  The public
    ``app.main.app`` wraps it in the static-file handler the development
    server installs, which short-circuits ``/static`` before any middleware
    runs; no test asks for a static path, so the wrapper only adds a layer
    to step through.
    """
    from app.main import application

    return application


class APIClient:
    """Drives the ASGI application over an in-process transport."""

    def __init__(self, application: Any = None,
                 base_url: str = 'http://testserver') -> None:
        self.application = (
            application if application is not None else _default_application()
        )
        self.forced_user: Any = None
        self.forced_token: Optional[str] = None
        self.default_headers: Dict[str, str] = {}
        self._transport = TestClient(
            _ScopeInjector(self.application, self),
            base_url=base_url,
            raise_server_exceptions=True,
            follow_redirects=False,
        )

    # -- authentication ---------------------------------------------------

    def force_authenticate(self, user: Any = None,
                           token: Optional[str] = None) -> None:
        """Authenticate every later request as ``user``.

        The object is handed to the application as-is; nothing is saved,
        reloaded or copied, so unsaved attribute changes are visible to the
        permission layer.
        """
        self.forced_user = user
        self.forced_token = token

    def force_login(self, user: Any) -> None:
        """Sign ``user`` in for both the API and the administration site.

        The API reads the forced object out of the scope, so identity is
        preserved exactly as :meth:`force_authenticate` promises.  The
        administration site does not look there -- it authenticates from a
        signed session cookie -- so the cookie is minted here too, which is
        what makes ``/admin/`` pages answer 200 instead of redirecting to
        the login form.
        """
        self.force_authenticate(user)
        identifier = getattr(user, 'id', None)
        if identifier is not None:
            from app import admin_site

            self._transport.cookies.set(
                admin_site.SESSION_COOKIE,
                admin_site._make_session(int(identifier)),
            )

    def logout(self) -> None:
        self.forced_user = None
        self.forced_token = None
        self.default_headers.clear()
        self._transport.cookies.clear()

    def credentials(self, **headers: str) -> None:
        """Set headers sent with every later request.

        Names arrive in the ``HTTP_AUTHORIZATION`` spelling the source
        suite uses and are translated back to ``Authorization``.
        """
        self.default_headers = {
            _header_name(name): value for name, value in headers.items()
        }

    @property
    def cookies(self) -> httpx.Cookies:
        return self._transport.cookies

    # -- verbs ------------------------------------------------------------

    def get(self, path: str, data: Optional[Dict[str, Any]] = None,
            **kwargs: Any) -> Response:
        return self.request('GET', path, data, **kwargs)

    def head(self, path: str, data: Optional[Dict[str, Any]] = None,
             **kwargs: Any) -> Response:
        return self.request('HEAD', path, data, **kwargs)

    def options(self, path: str, data: Optional[Dict[str, Any]] = None,
                **kwargs: Any) -> Response:
        return self.request('OPTIONS', path, data, **kwargs)

    def post(self, path: str, data: Optional[Dict[str, Any]] = None,
             **kwargs: Any) -> Response:
        return self.request('POST', path, data, **kwargs)

    def put(self, path: str, data: Optional[Dict[str, Any]] = None,
            **kwargs: Any) -> Response:
        return self.request('PUT', path, data, **kwargs)

    def patch(self, path: str, data: Optional[Dict[str, Any]] = None,
              **kwargs: Any) -> Response:
        return self.request('PATCH', path, data, **kwargs)

    def delete(self, path: str, data: Optional[Dict[str, Any]] = None,
               **kwargs: Any) -> Response:
        return self.request('DELETE', path, data, **kwargs)

    # -- the one that does the work ---------------------------------------

    def request(
        self,
        method: str,
        path: str,
        data: Optional[Dict[str, Any]] = None,
        format: Optional[str] = None,
        content_type: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        follow_redirects: bool = False,
        **extra: Any
    ) -> Response:
        """Issue one request and wrap the result.

        ``data`` becomes the query string for the read verbs and the body
        for the rest.  ``format='json'`` switches the body encoding;
        anything else uses ``multipart/form-data``.  ``extra`` accepts the
        ``HTTP_``-prefixed header spelling for a single call.
        """
        verb = method.upper()
        request_headers = dict(self.default_headers)
        for name, value in extra.items():
            request_headers[_header_name(name)] = value
        if headers:
            request_headers.update(headers)

        params = None
        content = None
        if verb in _QUERY_METHODS:
            params = data or None
        elif data is not None or verb in _BODY_METHODS:
            if format == 'json' or content_type == JSON_CONTENT:
                content = _encode_json(data)
                request_headers.setdefault('Content-Type', JSON_CONTENT)
            else:
                content = encode_multipart(data)
                request_headers.setdefault(
                    'Content-Type', content_type or MULTIPART_CONTENT)

        raw = self._transport.request(
            verb,
            path,
            params=params,
            content=content,
            headers=request_headers or None,
            follow_redirects=follow_redirects,
        )
        return Response(raw)


def _header_name(name: str) -> str:
    """Translate ``HTTP_ACCEPT_LANGUAGE`` into ``Accept-Language``."""
    stripped = name[5:] if name.upper().startswith('HTTP_') else name
    return '-'.join(part.capitalize() for part in stripped.split('_'))
