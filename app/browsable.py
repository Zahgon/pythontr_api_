"""HTML representation of an API response, selected by ``Accept``.

The baseline offered two renderers on every view: a JSON one and an HTML
"browsable API" one.  A client that prefers ``text/html`` therefore receives
``200 text/html; charset=utf-8`` with a navigable page, a ``csrftoken`` cookie
and ``Vary: Accept, Cookie``; a client that sends ``*/*`` or
``application/json`` receives the JSON representation.  Dropping the HTML
renderer changed what a browser sees on every endpoint, which is why it is
ported here rather than left out.

Byte-identity with the baseline's page is impossible by construction: every
byte of it came from the upstream framework's own template pack, and it names
that framework in its title, in its navbar and in each of its
``/static/rest_framework/...`` asset URLs -- the one thing this port is
forbidden to emit.  This module therefore ports the *function* -- the same
status, the same header profile, the same cookie, and a page carrying the same
request line, response line, response headers and payload -- and the report
records the body difference openly instead of hiding it.  That is the decision
already taken for ``/admin/`` in MIGRATION_REPORT.md section 3.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from html import escape
from http import HTTPStatus
from string import Template
from typing import Any, Dict, Optional

from starlette.requests import Request
from starlette.responses import Response

CSRF_COOKIE = 'csrftoken'
CSRF_MAX_AGE = 31449600
CSRF_SECRET_LENGTH = 32

MEDIA_TYPE = 'text/html'

_PAGE = Template("""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta http-equiv="Content-Type" content="text/html; charset=utf-8"/>
    <meta name="robots" content="NONE,NOARCHIVE" />
    <title>$title</title>
  </head>
  <body>
    <div class="wrapper">
      <ul class="breadcrumb">
$breadcrumbs      </ul>
      <div id="content" role="main" aria-label="content">
        <div class="page-header"><h1>$title</h1></div>
        <div class="request-info" aria-label="request info">
          <pre class="prettyprint"><b>$method</b> $path</pre>
        </div>
        <div class="response-info" aria-label="response info">
          <pre class="prettyprint"><span class="meta nocode"><b>HTTP $status $reason</b>
$headers
</span>$payload</pre>
        </div>
      </div>
    </div>
  </body>
</html>
""")

_SHOWN_HEADERS = ('Allow', 'Content-Type', 'Vary', 'WWW-Authenticate')


def wants_html(accept: str) -> bool:
    """Would the baseline's negotiation pick the HTML renderer for ``accept``?

    The renderer list is ordered JSON first, so an unweighted ``*/*`` or an
    absent header selects JSON.  Client media types are considered by
    descending quality, and the first one a renderer can serve wins, so an
    ``Accept`` naming ``text/html`` ahead of (or level with) anything JSON can
    satisfy selects the HTML renderer.
    """
    if not accept.strip():
        return False
    ranked = []
    for index, part in enumerate(accept.split(',')):
        pieces = part.split(';')
        media_range = pieces[0].strip().lower()
        if not media_range:
            continue
        quality = 1.0
        for piece in pieces[1:]:
            name, _, value = piece.partition('=')
            if name.strip().lower() == 'q':
                try:
                    quality = float(value)
                except ValueError:
                    quality = 1.0
        ranked.append((-quality, index, media_range))
    for _quality, _index, media_range in sorted(ranked):
        if media_range in ('text/html', 'text/*'):
            return True
        if media_range in ('*/*', 'application/json', 'application/*'):
            return False
    return False


def _breadcrumbs(path: str) -> str:
    parts = [segment for segment in path.split('/') if segment]
    rows = []
    href = ''
    for index, segment in enumerate(parts):
        href = '%s/%s' % (href, segment)
        active = ' class="active"' if index == len(parts) - 1 else ''
        rows.append('        <li%s><a href="%s/">%s</a></li>\n'
                    % (active, escape(href), escape(segment)))
    return ''.join(rows)


def _title(path: str) -> str:
    parts = [segment for segment in path.split('/') if segment]
    if not parts:
        return 'Api Root'
    tail = parts[-1]
    if tail.isdigit():
        return '%s Instance' % parts[-2].title()
    return '%s List' % tail.title()


def _payload_block(content: Any) -> str:
    if content is None:
        return ''
    body = json.dumps(content, ensure_ascii=False, indent=4, default=str)
    return escape(body)


def _header_block(headers: Dict[str, str]) -> str:
    lines = []
    for name in _SHOWN_HEADERS:
        value = headers.get(name)
        if value:
            lines.append('<b>%s:</b> <span class="lit">%s</span>'
                         % (escape(name), escape(value)))
    return '\n'.join(lines)


def render(
    request: Request,
    content: Any,
    status_code: int,
    headers: Dict[str, str],
) -> Response:
    """Return the HTML representation of ``content`` for ``request``."""
    from app.security import get_random_string

    try:
        reason = HTTPStatus(status_code).phrase
    except ValueError:
        reason = ''
    shown = dict(headers)
    shown['Content-Type'] = 'application/json'
    body = _PAGE.substitute(
        title=escape(_title(request.url.path)),
        breadcrumbs=_breadcrumbs(request.url.path),
        method=escape(request.method),
        path=escape(request.url.path),
        status=status_code,
        reason=escape(reason),
        headers=_header_block(shown),
        payload=_payload_block(content),
    )
    merged = dict(headers)
    merged['Vary'] = 'Accept, Cookie'
    response = Response(
        content=body,
        status_code=status_code,
        headers=merged,
        media_type='text/html; charset=utf-8',
    )
    token = request.cookies.get(CSRF_COOKIE) or get_random_string(
        CSRF_SECRET_LENGTH)
    expires = format_datetime(
        datetime.now(timezone.utc) + timedelta(seconds=CSRF_MAX_AGE),
        usegmt=True,
    )
    response.headers.append(
        'Set-Cookie',
        '%s=%s; expires=%s; Max-Age=%d; Path=/; SameSite=Lax'
        % (CSRF_COOKIE, token, expires, CSRF_MAX_AGE),
    )
    return response


def selected(request: Request) -> Optional[str]:
    return request.scope.get('renderer')
