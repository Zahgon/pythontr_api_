"""The project's route-name table and its ``reverse()`` helper.

Routes themselves are declared by the ``APIRouter`` objects in
:mod:`recipe.routers`, :mod:`user.routers`, :mod:`user.admin.routers` and
:mod:`app.admin_site`, and mounted by :func:`app.main.create_app` under
literal prefixes.  What this module adds is the *naming* layer: a stable
symbolic name for every addressable path, so callers -- overwhelmingly the
test suite -- can ask for ``'recipe:article-detail'`` instead of hardcoding
``'/api/recipe/articles/7/'``.

The table is written out literally rather than derived from the mounted
application.  Two reasons:

*   the names are part of the project's public contract and predate the
    current routing layer, so they must not drift when a router is
    refactored;
*   ``reverse`` has to work in modules that are imported before the
    application object is built -- several test modules compute their URL
    constants at import time.

Names are colon separated: ``<namespace>[:<sub-namespace>]:<name>``.
Collection routes end in ``-list`` and single-row routes in ``-detail``,
which is the convention the router-generated names have always followed.

One historical wart is preserved: ``user:reset-password-confirm`` is
registered twice, once for the bare confirm endpoint and once for the
link-carrying variant.  ``reverse`` disambiguates them by argument count,
which is what the original name resolver did.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from starlette.convertors import Convertor, register_url_convertor


class NoDotConvertor(Convertor):
    """A path parameter that stops at a dot, as the baseline's did.

    The routers that generated the ``recipe`` and ``user/admin`` trees built
    every lookup value as ``[^/.]+``.  Keeping the dot out is what leaves
    ``/api/recipe/categories/5.json`` unmatched by the detail route and free
    for the format-suffix form to claim; the stock converter swallows the
    dot and turns the same request into a trailing-slash redirect.
    """

    regex = '[^/.]+'

    def convert(self, value: str) -> str:
        return value

    def to_string(self, value: Any) -> str:
        return str(value)


#: Registered on import so the router modules can spell ``{pk:nodot}``
#: whether they are imported through the application factory or directly,
#: which is how most of the test suite reaches them.
NODOT = 'nodot'
register_url_convertor(NODOT, NoDotConvertor())


#: The two trees the baseline mounted with a router; only those carried the
#: generated ``.json`` / ``.api`` twin for every route.  Everything under
#: ``/api/user`` proper was declared path by path and has no suffixed form.
FORMAT_SUFFIX_PREFIXES: Tuple[str, ...] = ('/api/recipe', '/api/user/admin')

#: ``<lookup>.<format>`` where the lookup may not contain a dot and the
#: format is lower case alphanumeric -- the baseline's generated pattern.
_SUFFIXED_SEGMENT = re.compile(r'^(?P<base>[^/.]*)\.(?P<format>[a-z0-9]+)$')


def split_format_suffix(path: str) -> Tuple[str, Optional[str]]:
    """Split a trailing ``.json``/``.api`` off ``path``.

    Returns the canonical trailing-slash path and the requested format, or
    ``(path, None)`` when the path carries nothing the baseline's suffix
    patterns would have matched -- an upper-case format, an empty one, a
    second dot, a prefix that never had a router.

    The empty lookup is accepted only directly under a router prefix, which
    is the router index itself: ``/api/recipe/.json`` resolved, while
    ``/api/recipe/categories/.json`` did not, because the collection's
    suffixed form is ``/api/recipe/categories.json``.
    """
    if not any(path == prefix or path.startswith(prefix + '/')
               for prefix in FORMAT_SUFFIX_PREFIXES):
        return path, None
    trimmed = path[:-1] if path.endswith('/') and len(path) > 1 else path
    head, _sep, segment = trimmed.rpartition('/')
    match = _SUFFIXED_SEGMENT.match(segment)
    if match is None:
        return path, None
    base = match.group('base')
    if not base and head not in FORMAT_SUFFIX_PREFIXES:
        return path, None
    return '{}/{}'.format(head, base).rstrip('/') + '/', match.group('format')


def suffixed(url: str, suffix: Optional[str]) -> str:
    """Render ``url`` in the form a router index would have hyperlinked.

    Reached from a suffixed index the baseline carried the suffix into every
    link it emitted, so ``/api/recipe/.json`` advertised
    ``/api/recipe/categories.json`` rather than the trailing-slash form.
    """
    if not suffix:
        return url
    return '{}.{}'.format(url.rstrip('/'), suffix)


class NoReverseMatch(Exception):
    """Raised when a route name -- or its arguments -- cannot be resolved.

    Deliberately defined here rather than imported: the naming layer owns
    its own failure mode, and nothing outside this module needs to know
    where it came from.
    """


#: ``(name, template, parameter names)`` for every addressable path.
#:
#: ``template`` uses ``str.format`` placeholders whose keys are exactly the
#: entries of the third element, in order, so a route can be reversed from
#: positional arguments or from keyword arguments interchangeably.
ROUTES: Tuple[Tuple[str, str, Tuple[str, ...]], ...] = (
    # -- administration site ------------------------------------------
    ('admin:index', '/admin/', ()),
    ('admin:login', '/admin/login/', ()),
    ('admin:core_user_changelist', '/admin/core/user/', ()),
    ('admin:core_user_add', '/admin/core/user/add/', ()),
    ('admin:core_user_change', '/admin/core/user/{object_id}/change/',
     ('object_id',)),

    # -- user ----------------------------------------------------------
    ('user:create', '/api/user/create/', ()),
    ('user:token', '/api/user/token/', ()),
    ('user:me', '/api/user/me/', ()),
    ('user:activate', '/api/user/activate/{code}/', ('code',)),
    ('user:resend-activation', '/api/user/resend-activation/', ()),
    ('user:reset-password', '/api/user/reset-password/', ()),
    ('user:reset-password-confirm', '/api/user/reset-password/confirm/', ()),
    ('user:reset-password-confirm',
     '/api/user/reset-password/confirm/{uidb64}/{token}/',
     ('uidb64', 'token')),

    # -- user administration API ---------------------------------------
    ('user:admin:users-list', '/api/user/admin/users/', ()),
    ('user:admin:users-detail', '/api/user/admin/users/{pk}/', ('pk',)),
    ('user:admin:page-visits-list', '/api/user/admin/page-visits/', ()),
    ('user:admin:page-visits-detail',
     '/api/user/admin/page-visits/{pk}/', ('pk',)),

    # -- recipe --------------------------------------------------------
    ('recipe:category-list', '/api/recipe/categories/', ()),
    ('recipe:category-detail', '/api/recipe/categories/{pk}/', ('pk',)),
    ('recipe:article-list', '/api/recipe/articles/', ()),
    ('recipe:article-detail', '/api/recipe/articles/{pk}/', ('pk',)),
    ('recipe:slider-list', '/api/recipe/sliders/', ()),
    ('recipe:slider-detail', '/api/recipe/sliders/{pk}/', ('pk',)),
    ('recipe:comment-list', '/api/recipe/comments/', ()),
    ('recipe:comment-detail', '/api/recipe/comments/{pk}/', ('pk',)),
    ('recipe:message-list', '/api/recipe/messages/', ()),
    ('recipe:message-detail', '/api/recipe/messages/{pk}/', ('pk',)),
)


def _index() -> Dict[str, List[Tuple[str, Tuple[str, ...]]]]:
    """Group the table by name, preserving declaration order per name."""
    grouped: Dict[str, List[Tuple[str, Tuple[str, ...]]]] = {}
    for name, template, params in ROUTES:
        grouped.setdefault(name, []).append((template, params))
    return grouped


_BY_NAME = _index()

#: Every registered name, in declaration order and without duplicates.
ROUTE_NAMES: Tuple[str, ...] = tuple(_BY_NAME)


def route_names() -> Tuple[str, ...]:
    """Return every name :func:`reverse` accepts."""
    return ROUTE_NAMES


def _describe(name: str) -> str:
    """Render the candidate arities of ``name`` for an error message."""
    return ', '.join(
        '{} argument(s)'.format(len(params))
        for _template, params in _BY_NAME[name]
    )


def reverse(
    name: str,
    args: Optional[Sequence[Any]] = None,
    kwargs: Optional[Dict[str, Any]] = None,
) -> str:
    """Return the path registered under ``name``.

    ``args`` fills the route's placeholders positionally, ``kwargs`` fills
    them by name; supplying both is an error.  When a name is registered
    more than once the candidate whose placeholder count matches the
    supplied arguments wins, which is how the duplicated
    ``user:reset-password-confirm`` entry resolves to the bare endpoint
    with no arguments and to the link-carrying endpoint with two.

    Raises :class:`NoReverseMatch` when the name is unknown or when no
    candidate accepts the arguments given.
    """
    if args and kwargs:
        raise NoReverseMatch(
            "Don't mix *args and **kwargs in call to reverse()!")

    candidates = _BY_NAME.get(name)
    if candidates is None:
        raise NoReverseMatch(
            "Reverse for '{}' not found. '{}' is not a registered route "
            'name.'.format(name, name))

    if kwargs:
        wanted = set(kwargs)
        for template, params in candidates:
            if set(params) == wanted:
                return template.format(**{
                    key: _stringify(value) for key, value in kwargs.items()
                })
        raise NoReverseMatch(
            "Reverse for '{}' with keyword arguments '{}' not found. "
            '{} pattern(s) tried: {}.'.format(
                name, sorted(wanted), len(candidates), _describe(name)))

    values = list(args or ())
    for template, params in candidates:
        if len(params) == len(values):
            return template.format(**{
                key: _stringify(value)
                for key, value in zip(params, values)
            })
    raise NoReverseMatch(
        "Reverse for '{}' with {} argument(s) not found. "
        '{} pattern(s) tried: {}.'.format(
            name, len(values), len(candidates), _describe(name)))


def _stringify(value: Any) -> str:
    """Render a single URL argument.

    Model instances are addressed by their primary key, which is what the
    callers pass when they hand a row straight to ``reverse``.
    """
    if hasattr(value, 'pk'):
        return str(getattr(value, 'pk'))
    if hasattr(value, 'id') and not isinstance(value, (str, bytes, int)):
        return str(getattr(value, 'id'))
    return str(value)
