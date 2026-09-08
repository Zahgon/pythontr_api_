"""The project's page envelope.

``app.wire.paginate`` is what the routers call; this class is the named
entry point ``settings.API['DEFAULT_PAGINATION_CLASS']`` points at, and it
keeps the envelope's shape in one place.

Two details are load bearing and reproduced exactly:

*   key order -- ``count``, ``first_page``, ``last_page``, ``next``,
    ``previous``, ``last_page_number``, ``current_page``, ``results`` --
    because clients read the payload positionally in a couple of places;
*   the links are rewritten path-relative, ``first_page`` is ``previous``
    with its page parameter stripped, and ``last_page`` is ``next`` with
    its page number replaced by the final page number.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

PAGE_QUERY_PARAM = 'page'

_PAGE_RE = re.compile(r'\?page=\d+')


def relative(link: Optional[str]) -> Optional[str]:
    """Strip scheme and host, keeping the path and its query string."""
    if not link:
        return None
    return '/{}'.format(link.split('/', 3)[-1])


class CustomPagination:
    """Page number paginator returning the project's historical envelope."""

    page_size = 27
    page_query_param = PAGE_QUERY_PARAM

    def __init__(self, page: Any = None) -> None:
        self.page = page

    def get_next_link(self) -> Optional[str]:
        return getattr(self.page, 'next_link', None)

    def get_previous_link(self) -> Optional[str]:
        return getattr(self.page, 'previous_link', None)

    def get_paginated_response(self, data: List[Any]) -> Dict[str, Any]:
        current_page_number = self.page.number
        next_link = relative(self.get_next_link())
        previous_link = relative(self.get_previous_link())

        first_page = _PAGE_RE.sub(
            '', previous_link) if previous_link else None
        last_page = _PAGE_RE.sub(
            '?page={}'.format(self.page.paginator.num_pages),
            next_link) if next_link else None

        return {
            'count': self.page.paginator.count,
            'first_page': first_page,
            'last_page': last_page,
            'next': next_link,
            'previous': previous_link,
            'last_page_number': self.page.paginator.num_pages,
            'current_page': current_page_number,
            'results': data,
        }
