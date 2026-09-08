"""Application factory.

Builds the public ASGI object ``app.main:app``.

The middleware stack is registered innermost-first because Starlette treats the
*last* registered middleware as the outermost layer.  Reading the calls in
``_install_middleware`` bottom-to-top therefore gives the request order:

    FormatSuffix -> Security -> Session -> Common -> Csrf -> Authentication
                 -> Message -> XFrameOptions -> Locale -> NotFound -> Allow
                 -> Exception

That ordering is load-bearing.  ``CommonMiddleware`` answers a missing trailing
slash with a 301 *without* calling the layers beneath it, which is why such a
redirect carries the three security headers but no ``X-Frame-Options``,
``Content-Language`` or ``Vary``.
"""

from __future__ import annotations

import os
from typing import Any, Dict

from fastapi import APIRouter, FastAPI, Request
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles

from app import settings
from app.wire import not_found_page
from app.middleware import (
    AllowHeaderMiddleware,
    AuthenticationMiddleware,
    CommonMiddleware,
    CsrfViewMiddleware,
    ExceptionMiddleware,
    FormatSuffixMiddleware,
    LocaleMiddleware,
    MessageMiddleware,
    NotFoundMiddleware,
    SecurityMiddleware,
    SessionMiddleware,
    XFrameOptionsMiddleware,
)

API_PREFIX = '/api'
RECIPE_PREFIX = API_PREFIX + '/recipe'
USER_PREFIX = API_PREFIX + '/user'
ADMIN_API_PREFIX = USER_PREFIX + '/admin'


def _install_middleware(application: FastAPI) -> None:
    """Register the stack.  First call is innermost, last call is outermost."""
    application.add_middleware(ExceptionMiddleware)
    application.add_middleware(AllowHeaderMiddleware)
    application.add_middleware(NotFoundMiddleware)
    application.add_middleware(LocaleMiddleware)
    application.add_middleware(XFrameOptionsMiddleware)
    application.add_middleware(MessageMiddleware)
    application.add_middleware(AuthenticationMiddleware)
    application.add_middleware(CsrfViewMiddleware)
    application.add_middleware(CommonMiddleware)
    application.add_middleware(SessionMiddleware)
    application.add_middleware(SecurityMiddleware)
    application.add_middleware(FormatSuffixMiddleware)


def _install_routers(application: FastAPI) -> None:
    """Mount every ``APIRouter`` under the same prefixes the original served."""
    from recipe import routers as recipe_routers

    application.include_router(recipe_routers.router, prefix=RECIPE_PREFIX)

    try:
        from user import routers as user_routers
    except ImportError:
        user_routers = None
    if user_routers is not None:
        application.include_router(user_routers.router, prefix=USER_PREFIX)

    try:
        from user.admin import routers as user_admin_routers
    except ImportError:
        user_admin_routers = None
    if user_admin_routers is not None:
        application.include_router(
            user_admin_routers.router, prefix=ADMIN_API_PREFIX
        )

    try:
        from app import admin_site
    except ImportError:
        admin_site = None
    if admin_site is not None:
        application.include_router(admin_site.router)


def _static_directory() -> str:
    for directory in settings.STATICFILES_DIRS:
        if os.path.isdir(directory):
            return str(directory)
    return ''


class StaticFilesHandler:
    """Serve ``/static`` *outside* the middleware stack.

    The baseline's development server wraps the application in a static
    handler, so a request for a static path never reaches any middleware.
    That is why a missing file answers with only ``Content-Type`` and
    ``Content-Length`` and carries none of the locale or security headers
    every other response gets.  Mounting the files inside the application
    would run the whole stack over them and add six headers the original
    never sends.

    The baseline only installs that handler while ``DEBUG`` is on, so with
    ``DEBUG`` off a static path is resolved by the URL configuration like any
    other and its 404 does carry the full header set.  ``install_static``
    below reproduces that condition.
    """

    def __init__(self, application: FastAPI, prefix: str, directory: str):
        self.application = application
        self.prefix = prefix
        self.files = (
            StaticFiles(directory=directory, check_dir=False)
            if directory else None
        )

    async def __call__(self, scope: Dict[str, Any], receive: Any,
                       send: Any) -> None:
        if scope.get('type') == 'http' and \
                scope.get('path', '').startswith(self.prefix):
            await self._serve(scope, receive, send)
            return
        await self.application(scope, receive, send)

    async def _serve(self, scope: Dict[str, Any], receive: Any,
                     send: Any) -> None:
        if self.files is not None:
            inner = dict(scope)
            inner['path'] = '/' + scope['path'][len(self.prefix):].lstrip('/')
            try:
                await self.files(inner, receive, send)
                return
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
        request = Request(scope, receive)
        # The baseline's static handler raises Http404 carrying the path it
        # looked for, relative to the static root, and that message is what
        # the 404 page shows instead of the resolver hint.
        missing = scope['path'][len(self.prefix):].lstrip('/')
        response = Response(
            content=not_found_page(
                request, exception_value="'%s' could not be found" % missing),
            status_code=404,
            media_type='text/html; charset=utf-8',
        )
        await response(scope, receive, send)


class MethodNormalizationHandler:
    """Upper-cases the request method and lets unknown verbs reach the views.

    The baseline reads ``REQUEST_METHOD`` and upper-cases it, so ``get`` is a
    plain ``GET``.  It also resolves a URL before it resolves a method, so an
    unknown verb on a known path is authenticated first and only then rejected
    -- an anonymous caller gets ``401``, not ``405``.  Starlette does the
    opposite on both counts, hence this wrapper and ``_open_method_catch_alls``.
    """

    def __init__(self, application: Any):
        self.application = application

    async def __call__(self, scope: Dict[str, Any], receive: Any,
                       send: Any) -> None:
        if scope.get('type') == 'http':
            method = scope.get('method', '')
            if method != method.upper():
                scope = dict(scope)
                scope['method'] = method.upper()
        await self.application(scope, receive, send)


def _open_method_catch_alls(application: FastAPI) -> None:
    for route in application.routes:
        if getattr(route, 'status_code', None) == 405:
            route.methods = None


def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.APLICATION_NAME,
        debug=settings.DEBUG,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    _install_routers(application)
    _open_method_catch_alls(application)
    _install_middleware(application)
    return application


def install_static(application: FastAPI) -> Any:
    if not settings.DEBUG:
        return application
    return StaticFilesHandler(
        application,
        (settings.STATIC_URL.rstrip('/') or '/static') + '/',
        _static_directory(),
    )


application = create_app()
app = MethodNormalizationHandler(install_static(application))
