"""HTTP wire helpers shared by every router in the project.

This module is deliberately small.  It does not implement a view layer, a
serializer layer or a router layer -- FastAPI provides all three.  What it
provides is the handful of *response shaping* rules the public API of this
project has always had and which FastAPI does not supply out of the box:

* compact JSON (``,``/``:`` separators, ``ensure_ascii=False``, no trailing
  newline),
* the error envelopes the clients of this API parse,
* the page envelope with its historical key order,
* the ``Allow`` value for the current path, stamped onto every response by
  :mod:`app.middleware` including error responses.
"""
from __future__ import annotations

import json
import re
from html import escape
from typing import Any, Dict, Iterable, List, Optional, Sequence
from urllib.parse import urljoin

from starlette.requests import Request
from starlette.responses import Response

from app import settings
from app.i18n import gettext as _

__all__ = [
    'JSONResponse',
    'ApiError',
    'NotAuthenticated',
    'AuthenticationFailed',
    'PermissionDenied',
    'MethodNotAllowed',
    'NotFound',
    'ValidationFailed',
    'UnsupportedMediaType',
    'NotAcceptable',
    'set_allow',
    'get_allow',
    'paginate',
    'page_size',
    'not_found_page',
    'bad_request_page',
    'server_error_page',
]


class JSONResponse(Response):
    """JSON response with the byte layout this API has always emitted."""

    media_type = 'application/json'

    def render(self, content: Any) -> bytes:
        if content is None:
            return b''
        return json.dumps(
            content,
            ensure_ascii=False,
            separators=(',', ':'),
            default=str,
        ).encode('utf-8')


class ApiError(Exception):
    """An error that renders as a JSON body with a known status code."""

    status_code = 500
    default_detail = 'Sunucu hatası.'

    def __init__(
        self,
        detail: Any = None,
        status_code: Optional[int] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        if detail is None:
            detail = self.default_detail
        if status_code is not None:
            self.status_code = status_code
        self.detail = detail
        self.headers = headers or {}
        super().__init__(str(detail))

    def body(self) -> Any:
        if isinstance(self.detail, (dict, list)):
            return self.detail
        return {'detail': self.detail}


class NotAuthenticated(ApiError):
    """No usable credentials were offered.

    The status code is 401 when the view's first authenticator advertises a
    scheme and 403 when it does not.  The cookie authenticator advertises no
    scheme, so views that list it first answer 403 -- see PORT_PLAN.md 4.
    """

    status_code = 401

    def __init__(self, detail: Any = None, auth_header: Optional[str] = 'Token'):
        headers = {'WWW-Authenticate': auth_header} if auth_header else None
        super().__init__(
            detail if detail is not None else _('Authentication credentials were not provided.'),
            status_code=401 if auth_header else 403,
            headers=headers,
        )


class AuthenticationFailed(ApiError):
    status_code = 401

    def __init__(self, detail: Any = None, auth_header: Optional[str] = 'Token'):
        headers = {'WWW-Authenticate': auth_header} if auth_header else None
        super().__init__(
            detail if detail is not None else _('Invalid token.'),
            status_code=401 if auth_header else 403,
            headers=headers,
        )


class PermissionDenied(ApiError):
    status_code = 403

    def __init__(self, detail: Any = None):
        super().__init__(
            detail if detail is not None
            else _('You do not have permission to perform this action.')
        )


class MethodNotAllowed(ApiError):
    status_code = 405

    def __init__(self, method: str):
        super().__init__(_('Method "{method}" not allowed.').format(method=method))


class NotFound(ApiError):
    status_code = 404

    def __init__(self, detail: Any = None):
        super().__init__(detail if detail is not None else _('Not found.'))


class ValidationFailed(ApiError):
    status_code = 400

    def __init__(self, detail: Any):
        super().__init__(detail)


class NotAcceptable(ApiError):
    status_code = 406

    def __init__(self) -> None:
        super().__init__(_('Could not satisfy the request Accept header.'))


class UnsupportedMediaType(ApiError):
    status_code = 415

    def __init__(self, media_type: str):
        super().__init__(
            _('Unsupported media type "{media_type}" in request.').format(
                media_type=media_type,
            )
        )


# ---------------------------------------------------------------------------
# Allow header
# ---------------------------------------------------------------------------

def set_allow(request: Request, methods: Sequence[str]) -> None:
    """Record the methods this path serves so every response can advertise them.

    The value is stamped by :mod:`app.middleware` onto success responses and
    onto 401/403/405 bodies alike, which is what the baseline does.
    """
    request.scope['allow_methods'] = tuple(methods)


def get_allow(request: Request) -> Optional[str]:
    methods = request.scope.get('allow_methods')
    if not methods:
        return None
    return ', '.join(methods)


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

_PAGE_RE = re.compile(r'\?page=\d+')


def page_size() -> Optional[int]:
    """Return the configured page size, or ``None`` when paging is disabled."""
    from app import settings

    return settings.API.get('PAGE_SIZE')


def _link(request: Request, page_number: Optional[int]) -> Optional[str]:
    if page_number is None:
        return None
    params = dict(request.query_params)
    if page_number == 1:
        params.pop('page', None)
    else:
        params['page'] = str(page_number)
    query = '&'.join('{}={}'.format(k, v) for k, v in params.items())
    path = request.url.path
    return '{}?{}'.format(path, query) if query else path


def paginate(request: Request, results: List[Any]) -> Dict[str, Any]:
    """Wrap ``results`` in the historical page envelope.

    Key order is load bearing: clients read the payload positionally in a few
    places.  ``first_page`` is the previous link with its page parameter
    removed; ``last_page`` is the next link with its page number replaced by
    the final page number.
    """
    size = page_size()
    if not size:
        return {'results': results, 'unpaginated': True}

    count = len(results)
    num_pages = max(1, (count + size - 1) // size)
    raw_page = request.query_params.get('page')
    if raw_page in (None, ''):
        number = 1
    elif raw_page == 'last':
        number = num_pages
    else:
        try:
            number = int(raw_page)
        except (TypeError, ValueError):
            raise NotFound(_('Invalid page.'))
        if number < 1 or number > num_pages:
            raise NotFound(_('Invalid page.'))

    start = (number - 1) * size
    page_items = results[start:start + size]

    next_link = _link(request, number + 1) if number < num_pages else None
    previous_link = _link(request, number - 1) if number > 1 else None

    first_page = _PAGE_RE.sub('', previous_link) if previous_link else None
    last_page = (
        _PAGE_RE.sub('?page={}'.format(num_pages), next_link) if next_link else None
    )

    return {
        'count': count,
        'first_page': first_page,
        'last_page': last_page,
        'next': next_link,
        'previous': previous_link,
        'last_page_number': num_pages,
        'current_page': number,
        'results': page_items,
    }


# ---------------------------------------------------------------------------
# Framework HTML pages
# ---------------------------------------------------------------------------

_NOT_FOUND_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <title>Page not found at {path}</title>
  <meta name="robots" content="NONE,NOARCHIVE">
  <style type="text/css">
    html * {{ padding:0; margin:0; }}
    body * {{ padding:10px 20px; }}
    body {{ font:small sans-serif; background:#eee; color:#000; }}
    #summary {{ background: #ffc; }}
    #info {{ background:#f6f6f6; }}
    #explanation {{ background:#eee; border-bottom: 0px none; }}
  </style>
</head>
<body>
  <div id="summary">
    <h1>Page not found <span>(404)</span></h1>
    <table class="meta">
      <tr><th>Request Method:</th><td>{method}</td></tr>
      <tr><th>Request URL:</th><td>{url}</td></tr>
    </table>
  </div>
  <div id="info">
    <p>
      {resolver}
      didn\u2019t match any of these.
    </p>
  </div>
  <div id="explanation">
    <p>You're seeing this error because <code>DEBUG = True</code> in your
    settings file. Change that to <code>False</code>, and this page will
    display a standard 404 page.</p>
  </div>
</body>
</html>
"""

# The resolver hint is replaced by the raised message whenever the 404 came
# from an ``Http404`` that carried one -- which is how the static handler
# reports a missing file.
_NOT_FOUND_EXCEPTION_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <title>Page not found at {path}</title>
  <meta name="robots" content="NONE,NOARCHIVE">
  <style type="text/css">
    html * {{ padding:0; margin:0; }}
    body * {{ padding:10px 20px; }}
    body {{ font:small sans-serif; background:#eee; color:#000; }}
    #summary {{ background: #ffc; }}
    #info {{ background:#f6f6f6; }}
    #explanation {{ background:#eee; border-bottom: 0px none; }}
    pre.exception_value {{ font-family: sans-serif; color: #575757; font-size: 1.5em; margin: 10px 0 10px 0; }}
  </style>
</head>
<body>
  <div id="summary">
    <h1>Page not found <span>(404)</span></h1>
    <pre class="exception_value">{value}</pre>
    <table class="meta">
      <tr><th>Request Method:</th><td>{method}</td></tr>
      <tr><th>Request URL:</th><td>{url}</td></tr>
    </table>
  </div>
  <div id="explanation">
    <p>You're seeing this error because <code>DEBUG = True</code> in your
    settings file. Change that to <code>False</code>, and this page will
    display a standard 404 page.</p>
  </div>
</body>
</html>
"""


_SERVER_ERROR_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <title>{summary}</title>
  <meta name="robots" content="NONE,NOARCHIVE">
</head>
<body>
  <div id="summary">
    <h1>Server Error <span>({path})</span></h1>
    <pre class="exception_value">{value}</pre>
  </div>
  <div id="traceback">
    <h2>Traceback <span>Switch to copy-and-paste view</span></h2>
    <pre>{traceback}</pre>
  </div>
</body>
</html>
"""


# The two pages above are the *debug* pages: they disclose the request URL, the
# resolver hint and the traceback, and the baseline only ever renders them while
# DEBUG is on.  With DEBUG off the baseline falls back to this one generic
# template instead, filled in with a title and a detail sentence.  The leading
# newline is part of it, and it is what makes the rendered 404 exactly 179 bytes
# and the rendered 500 exactly 145.
_ERROR_PAGE_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <title>{title}</title>
</head>
<body>
  <h1>{title}</h1><p>{details}</p>
</body>
</html>
"""


def not_found_page(request: Request,
                   exception_value: Optional[str] = None) -> str:
    if not settings.DEBUG:
        return _ERROR_PAGE_TEMPLATE.format(
            title='Not Found',
            details='The requested resource was not found on this server.',
        )
    path = request.url.path
    full_path = '%s?%s' % (path, request.url.query) if request.url.query else path
    common = {
        'path': escape(path),
        'method': escape(request.method),
        # The absolute URL is resolved against the request URI, which removes
        # dot segments (RFC 3986 5.2.4); the reported path keeps them.
        'url': escape(urljoin(str(request.url), full_path)),
    }
    if exception_value is not None:
        return _NOT_FOUND_EXCEPTION_TEMPLATE.format(
            value=escape(exception_value), **common)
    trimmed = path.lstrip('/')
    resolver = (
        'The empty path' if not trimmed
        else 'The current path, <code>%s</code>,' % escape(trimmed)
    )
    return _NOT_FOUND_TEMPLATE.format(resolver=resolver, **common)


def bad_request_page(request: Request, exc: BaseException, traceback_text: str) -> str:
    if not settings.DEBUG:
        return _ERROR_PAGE_TEMPLATE.format(title='Bad Request (400)', details='')
    return _technical_page(request, exc, traceback_text)


def _technical_page(request: Request, exc: BaseException,
                    traceback_text: str) -> str:
    # The baseline renders this page through an auto-escaping template engine,
    # so an exception message containing a quote reaches the client as
    # `&#x27;` rather than `'`.
    return _SERVER_ERROR_TEMPLATE.format(
        summary=escape('{} at {}'.format(type(exc).__name__,
                                         request.url.path)),
        path=escape(request.url.path),
        value=escape(str(exc)),
        traceback=escape(traceback_text),
    )


def server_error_page(request: Request, exc: BaseException, traceback_text: str) -> str:
    if not settings.DEBUG:
        return _ERROR_PAGE_TEMPLATE.format(title='Server Error (500)', details='')
    return _technical_page(request, exc, traceback_text)


def _render_html(request: Request) -> bool:
    return request.scope.get('renderer') == 'html'


def error_response(request: Request, exc: ApiError) -> Response:
    """Render an :class:`ApiError` with its headers and the path's Allow value."""
    headers = dict(exc.headers)
    allow = get_allow(request)
    if allow:
        headers.setdefault('Allow', allow)
    headers.setdefault('Vary', 'Accept')
    if _render_html(request):
        from app import browsable

        return browsable.render(request, exc.body(), exc.status_code, headers)
    return JSONResponse(exc.body(), status_code=exc.status_code, headers=headers)


def json_response(
    request: Request,
    content: Any,
    status_code: int = 200,
    headers: Optional[Dict[str, str]] = None,
) -> JSONResponse:
    merged = dict(headers or {})
    allow = get_allow(request)
    if allow:
        merged.setdefault('Allow', allow)
    # Content negotiation varies the representation on Accept; the framework
    # 404/500 pages are rendered outside a view and therefore do not.
    merged.setdefault('Vary', 'Accept')
    if status_code == 204:
        return Response(status_code=204, headers=merged)
    if _render_html(request):
        from app import browsable

        return browsable.render(request, content, status_code, merged)
    return JSONResponse(content, status_code=status_code, headers=merged)


def iter_errors(detail: Any) -> Iterable[str]:
    """Yield the leaf strings of a validation payload (used by tests)."""
    if isinstance(detail, dict):
        for value in detail.values():
            for item in iter_errors(value):
                yield item
    elif isinstance(detail, (list, tuple)):
        for value in detail:
            for item in iter_errors(value):
                yield item
    else:
        yield str(detail)
