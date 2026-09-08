"""Staff-facing admin API routers.

Mounted by ``app.main`` under ``/api/user/admin``. Every route authenticates
with :data:`app.deps.COOKIE_FIRST` because the baseline falls back to the
settings-level authenticator list whose first entry advertises no scheme, so an
anonymous caller is answered 403 without a ``WWW-Authenticate`` header rather
than 401.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, Request
from sqlalchemy import Select, func, select
from user_agents import parse as parse_user_agent

from app.deps import Access, COOKIE_FIRST, access, allow_any, is_admin_user
from app.i18n import gettext as _
from app.urls import suffixed
from app.wire import MethodNotAllowed, NotFound, ValidationFailed
from app.wire import json_response, paginate, page_size
from app.parsing import parse_body, validate
from core.models import Article, PageVisit, User
from recipe.routers import add_head_to_get_routes
from user.admin.schemas import (
    USER_ACTION_INPUT_ORDER,
    UserActionInput,
    serialize_admin_user_detail,
    serialize_admin_user_list,
    serialize_page_visit,
)

router = APIRouter()

ROOT_ALLOW = ('GET', 'HEAD', 'OPTIONS')
USERS_LIST_ALLOW = ('GET',)
USERS_DETAIL_ALLOW = ('GET', 'PATCH', 'DELETE')
ACTION_GET_ALLOW = ('GET', 'HEAD', 'OPTIONS')
ACTION_POST_ALLOW = ('POST', 'OPTIONS')

_ROOT_REST = ('POST', 'PUT', 'PATCH', 'DELETE')
_USERS_LIST_REST = ('POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS')
_USERS_DETAIL_REST = ('POST', 'PUT', 'OPTIONS')
_ACTION_GET_REST = ('POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS')
_ACTION_POST_REST = ('GET', 'PUT', 'PATCH', 'DELETE')
PAGE_VISITS_LIST_ALLOW = ('GET', 'POST', 'HEAD', 'OPTIONS')
_PAGE_VISITS_LIST_REST = ('PUT', 'PATCH', 'DELETE')
PAGE_VISITS_DETAIL_ALLOW = ('GET', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS')
_PAGE_VISITS_DETAIL_REST = ('POST',)

#: The metadata the baseline emits for ``OPTIONS`` on a page-visit that does
#: not exist.  When the lookup succeeds the baseline instead tries to describe
#: the writable fields and dies on the serializer, so this body only ever
#: reaches the wire on a 404 lookup.  Key order is part of the contract.
PAGE_VISIT_METADATA = {
    'name': 'Page Visit Instance',
    'description': '',
    'renders': ['application/json', 'text/html'],
    'parses': [
        'application/json',
        'application/x-www-form-urlencoded',
        'multipart/form-data',
    ],
}

BOT_KEYWORDS = (
    'bot', 'crawler', 'spider', 'ping', 'lighthouse', 'slurp', 'search',
    'surveillance', 'monitoring', 'analyzer', 'index', 'archive', 'scrape',
    'http', 'python-requests', 'curl', 'wget', 'phantom', 'headless',
    'selenium', 'mediapartners-google', 'adsbot-google',
)

LOCAL_ADDRESSES = ('127.0.0.1', '::1', 'localhost')

_CONTENT_ID_RE = re.compile(r'(.*?)-(\d+)$')


def listing(request: Request, rows: List[Any]) -> Any:
    payload = paginate(request, rows)
    if payload.get('unpaginated'):
        return payload['results']
    return payload


# --------------------------------------------------------------------------
# router root
# --------------------------------------------------------------------------

@router.get('/', status_code=200)
async def admin_root(
    request: Request,
    ctx: Access = Depends(access(allow_any, authenticators=COOKIE_FIRST, allow=ROOT_ALLOW)),
) -> Any:
    base = str(request.base_url).rstrip('/')
    suffix = request.scope.get('format_suffix')
    return json_response(request, {
        'users': suffixed('{}/api/user/admin/users/'.format(base), suffix),
        'page-visits': suffixed(
            '{}/api/user/admin/page-visits/'.format(base), suffix),
    })


@router.api_route('/', methods=list(_ROOT_REST), include_in_schema=False)
async def admin_root_rest(
    request: Request,
    ctx: Access = Depends(access(allow_any, authenticators=COOKIE_FIRST, allow=ROOT_ALLOW)),
) -> Any:
    raise MethodNotAllowed(request.method)


# --------------------------------------------------------------------------
# users
# --------------------------------------------------------------------------

def _users_queryset(request: Request) -> Select:
    statement = select(User).order_by(User.created_at.desc())
    params = request.query_params
    search = params.get('search')
    if search:
        pattern = '%{}%'.format(search)
        statement = statement.where(
            User.email.ilike(pattern) | User.name.ilike(pattern) | User.surname.ilike(pattern)
        )
    for field in ('is_active', 'is_staff', 'is_ban'):
        raw = params.get(field)
        if raw in ('true', 'True', '1'):
            statement = statement.where(getattr(User, field).is_(True))
        elif raw in ('false', 'False', '0'):
            statement = statement.where(getattr(User, field).is_(False))
    return statement


@router.get('/users/', status_code=200)
async def users_list(
    request: Request,
    ctx: Access = Depends(access(is_admin_user, authenticators=COOKIE_FIRST, allow=USERS_LIST_ALLOW)),
) -> Any:
    rows = list(ctx.session.scalars(_users_queryset(request)).unique())
    return json_response(request, listing(request, [serialize_admin_user_list(row) for row in rows]))


@router.api_route('/users/', methods=list(_USERS_LIST_REST), include_in_schema=False)
async def users_list_rest(
    request: Request,
    ctx: Access = Depends(access(is_admin_user, authenticators=COOKIE_FIRST, allow=USERS_LIST_ALLOW)),
) -> Any:
    raise MethodNotAllowed(request.method)


def _admin_user(ctx: Access, pk: str) -> User:
    """Fetch one user by primary key.

    The baseline overrides ``get_object`` with a bare ``.get()``, so a missing
    row raises rather than answering 404. Preserved.
    """
    row = ctx.session.scalars(select(User).where(User.id == int(pk))).first()
    if row is None:
        raise User.DoesNotExist('User matching query does not exist.')
    return row


@router.get('/users/{pk:nodot}/', status_code=200)
async def users_detail(
    request: Request,
    pk: str,
    ctx: Access = Depends(access(is_admin_user, authenticators=COOKIE_FIRST, allow=USERS_DETAIL_ALLOW)),
) -> Any:
    row = _admin_user(ctx, pk)
    return json_response(request, serialize_admin_user_detail(row))


@router.patch('/users/{pk:nodot}/', status_code=200)
async def users_patch(
    request: Request,
    pk: str,
    ctx: Access = Depends(access(is_admin_user, authenticators=COOKIE_FIRST, allow=USERS_DETAIL_ALLOW)),
) -> Any:
    row = _admin_user(ctx, pk)
    if row.id == ctx.user.id:
        return json_response(
            request,
            {'error': _('you_cannot_modify_your_own_account')},
            status_code=400,
        )
    data = await parse_body(request)
    payload = validate(UserActionInput, data, order=USER_ACTION_INPUT_ORDER)
    for field in USER_ACTION_INPUT_ORDER:
        value = getattr(payload, field)
        if value is not None:
            setattr(row, field, value)
    ctx.session.add(row)
    ctx.session.flush()
    return json_response(request, {
        'is_active': row.is_active,
        'is_staff': row.is_staff,
        'is_ban': row.is_ban,
        'is_delete': row.is_delete,
    })


@router.delete('/users/{pk:nodot}/', status_code=200)
async def users_delete(
    request: Request,
    pk: str,
    ctx: Access = Depends(access(is_admin_user, authenticators=COOKIE_FIRST, allow=USERS_DETAIL_ALLOW)),
) -> Any:
    row = _admin_user(ctx, pk)
    if row.id == ctx.user.id:
        return json_response(
            request,
            {'error': _('you_cannot_delete_your_own_account')},
            status_code=400,
        )
    row.is_delete = True
    ctx.session.add(row)
    ctx.session.flush()
    return json_response(request, None, status_code=204)


@router.api_route('/users/{pk:nodot}/', methods=list(_USERS_DETAIL_REST), include_in_schema=False)
async def users_detail_rest(
    request: Request,
    pk: str,
    ctx: Access = Depends(access(is_admin_user, authenticators=COOKIE_FIRST, allow=USERS_DETAIL_ALLOW)),
) -> Any:
    raise MethodNotAllowed(request.method)


# --------------------------------------------------------------------------
# page visits
# --------------------------------------------------------------------------

def _client_ip(request: Request) -> Optional[str]:
    headers = request.headers
    raw = headers.get('x-forwarded-for') or headers.get('x-real-ip')
    if not raw:
        client = request.client
        raw = client.host if client else None
    if not raw:
        return None
    return raw.split(',')[0].strip()


def _is_bot(ua_string: str, user_agent: Any) -> bool:
    lowered = (ua_string or '').lower()
    for keyword in BOT_KEYWORDS:
        if keyword in lowered:
            return True
    return bool(getattr(user_agent, 'is_bot', False))


async def _get_request_data(request: Request, ctx: Access) -> Optional[Dict[str, Any]]:
    """Collect the tracked attributes of one page view.

    Returns ``None`` for loopback callers. The caller subscripts the result
    without checking, so a request from 127.0.0.1 raises. Preserved.
    """
    ip = _client_ip(request)
    if ip in LOCAL_ADDRESSES:
        return None

    raw = await request.body()
    try:
        body = json.loads(raw.decode('utf-8')) if raw else {}
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}

    path = body.get('path', request.url.path)
    content_id: Optional[int] = None
    match = _CONTENT_ID_RE.search(path or '')
    if match:
        content_id = int(match.group(2))
        article = ctx.session.scalars(select(Article).where(Article.id == content_id)).first()
        if article is not None:
            article.read_count = (article.read_count or 0) + 1
            ctx.session.add(article)
            ctx.session.flush()

    cookies = request.cookies
    return {
        'path': path,
        'content_id': content_id,
        'referrer': body.get('referrer') or request.headers.get('referer'),
        'ip_address': ip,
        'language': (request.headers.get('accept-language') or 'en')[:10],
        'user_agent': request.headers.get('user-agent', ''),
        'ga_client_id': cookies.get('_ga'),
        'ga_session_id': cookies.get('_ga_369S5MD2X3'),
        'gads_id': cookies.get('__gads'),
        'gpi_uid': cookies.get('__gpi'),
    }


def _get_date_range(period: Optional[str]) -> Tuple[Optional[datetime], Optional[datetime]]:
    now = datetime.now(timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == 'day':
        return midnight, now
    if period == 'week':
        return midnight - timedelta(days=now.weekday()), now
    if period == 'month':
        return (now - timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0), now
    if period == 'year':
        return (now - timedelta(days=365)).replace(hour=0, minute=0, second=0, microsecond=0), now
    return None, None


def _filter_statement(statement: Select, request: Request, ctx: Access) -> Select:
    params = request.query_params
    start, end = _get_date_range(params.get('period'))
    if start is not None:
        statement = statement.where(PageVisit.timestamp >= start)
    if end is not None:
        statement = statement.where(PageVisit.timestamp <= end)
    user_id = getattr(ctx.user, 'id', None)
    if user_id:
        statement = statement.where(PageVisit.user_id == user_id)
    return statement


def _period_info(request: Request) -> Dict[str, Any]:
    params = request.query_params
    return {
        'period': params.get('period', 'all'),
        'start_date': params.get('start_date'),
        'end_date': params.get('end_date'),
    }


@router.get('/page-visits/', status_code=200)
async def page_visits_list(
    request: Request,
    ctx: Access = Depends(access(is_admin_user, authenticators=COOKIE_FIRST, allow=PAGE_VISITS_LIST_ALLOW)),
) -> Any:
    rows = list(ctx.session.scalars(
        select(PageVisit).order_by(PageVisit.timestamp.desc())
    ).unique())
    return json_response(request, listing(request, [serialize_page_visit(row) for row in rows]))


@router.api_route('/page-visits/', methods=list(_PAGE_VISITS_LIST_REST), include_in_schema=False)
async def page_visits_list_rest(
    request: Request,
    ctx: Access = Depends(access(is_admin_user, authenticators=COOKIE_FIRST, allow=PAGE_VISITS_LIST_ALLOW)),
) -> Any:
    raise MethodNotAllowed(request.method)


def _build_serializer_fields() -> None:
    """Fail the way the baseline fails when it builds the field map.

    Create, update and ``OPTIONS`` metadata all describe the writable fields
    before they look at the request body, so every one of them dies on the
    ``session_id`` column the model does not have - the body never matters.
    """
    serialize_page_visit(PageVisit())


@router.post('/page-visits/', status_code=201)
async def page_visits_create(
    request: Request,
    ctx: Access = Depends(access(is_admin_user, authenticators=COOKIE_FIRST, allow=PAGE_VISITS_LIST_ALLOW)),
) -> Any:
    _build_serializer_fields()
    return json_response(request, None, status_code=201)


@router.options('/page-visits/', include_in_schema=False)
async def page_visits_list_options(
    request: Request,
    ctx: Access = Depends(access(is_admin_user, authenticators=COOKIE_FIRST, allow=PAGE_VISITS_LIST_ALLOW)),
) -> Any:
    _build_serializer_fields()
    return json_response(request, PAGE_VISIT_METADATA)


@router.post('/page-visits/track_page_visit/', status_code=200)
async def track_page_visit(
    request: Request,
    ctx: Access = Depends(access(allow_any, authenticators=COOKIE_FIRST, allow=ACTION_POST_ALLOW)),
) -> Any:
    data = await _get_request_data(request, ctx)
    ua_string = data['user_agent']
    user_agent = parse_user_agent(ua_string)
    if _is_bot(ua_string, user_agent):
        return json_response(request, {'status': 'ignored', 'reason': 'bot_detected'})

    content_owner = None
    if data['content_id']:
        article = ctx.session.scalars(
            select(Article).where(Article.id == data['content_id'])
        ).first()
        if article is not None:
            content_owner = article.user

    if user_agent.is_mobile:
        device_type = 'mobile'
    elif user_agent.is_tablet:
        device_type = 'tablet'
    else:
        device_type = 'desktop'

    visit = PageVisit(
        user=content_owner,
        path=data['path'],
        content_id=data['content_id'],
        ip_address=data['ip_address'],
        user_agent=data['user_agent'],
        referrer=data['referrer'],
        method=request.method,
        device_type=device_type,
        language=data['language'],
        browser=user_agent.browser.family,
        os=user_agent.os.family,
        device_brand=user_agent.device.brand,
        device_model=user_agent.device.model,
        ga_client_id=data['ga_client_id'],
        ga_session_id=data['ga_session_id'],
        gads_id=data['gads_id'],
        gpi_uid=data['gpi_uid'],
    )
    ctx.session.add(visit)
    ctx.session.flush()
    return json_response(request, {'status': 'success'})


@router.api_route(
    '/page-visits/track_page_visit/', methods=list(_ACTION_POST_REST), include_in_schema=False
)
async def track_page_visit_rest(
    request: Request,
    ctx: Access = Depends(access(allow_any, authenticators=COOKIE_FIRST, allow=ACTION_POST_ALLOW)),
) -> Any:
    raise MethodNotAllowed(request.method)


def _distribution(ctx: Access, request: Request, column: Any, key: str) -> List[Dict[str, Any]]:
    statement = _filter_statement(
        select(column, func.count(PageVisit.id).label('count')), request, ctx
    ).group_by(column).order_by(func.count(PageVisit.id).desc())
    return [{key: row[0], 'count': row[1]} for row in ctx.session.execute(statement)]


@router.get('/page-visits/visitor_statistics/', status_code=200)
async def visitor_statistics(
    request: Request,
    ctx: Access = Depends(access(allow_any, authenticators=COOKIE_FIRST, allow=ACTION_GET_ALLOW)),
) -> Any:
    total = ctx.session.scalar(
        _filter_statement(select(func.count(PageVisit.id)), request, ctx)
    ) or 0

    pages_statement = _filter_statement(
        select(PageVisit.path, func.count(PageVisit.id).label('visit_count')), request, ctx
    ).group_by(PageVisit.path).order_by(func.count(PageVisit.id).desc()).limit(10)

    hours_statement = _filter_statement(
        select(
            func.extract('hour', PageVisit.timestamp).label('hour'),
            func.count(PageVisit.id).label('count'),
        ),
        request,
        ctx,
    ).group_by(func.extract('hour', PageVisit.timestamp)).order_by(
        func.extract('hour', PageVisit.timestamp)
    )

    return json_response(request, {
        'period_info': _period_info(request),
        'total_visits': total,
        'device_distribution': _distribution(ctx, request, PageVisit.device_type, 'device_type'),
        'browser_distribution': _distribution(ctx, request, PageVisit.browser, 'browser'),
        'os_distribution': _distribution(ctx, request, PageVisit.os, 'os'),
        'most_visited_pages': [
            {'path': row[0], 'visit_count': row[1]}
            for row in ctx.session.execute(pages_statement)
        ],
        'traffic_by_hour': [
            {'hour': int(row[0]), 'count': row[1]}
            for row in ctx.session.execute(hours_statement)
        ],
    })


@router.api_route(
    '/page-visits/visitor_statistics/', methods=list(_ACTION_GET_REST), include_in_schema=False
)
async def visitor_statistics_rest(
    request: Request,
    ctx: Access = Depends(access(allow_any, authenticators=COOKIE_FIRST, allow=ACTION_GET_ALLOW)),
) -> Any:
    raise MethodNotAllowed(request.method)


@router.get('/page-visits/content_performance/', status_code=200)
async def content_performance(
    request: Request,
    ctx: Access = Depends(access(allow_any, authenticators=COOKIE_FIRST, allow=ACTION_GET_ALLOW)),
) -> Any:
    """Aggregate per-article visit performance.

    The baseline averages a ``time_spent`` column that was never added to the
    model, so this endpoint has always raised. Preserved.
    """
    statement = _filter_statement(
        select(
            func.count(PageVisit.id).label('total_visits'),
            func.count(func.distinct(PageVisit.ip_address)).label('unique_visitors'),
            func.avg(PageVisit.time_spent).label('avg_time_spent'),
        ),
        request,
        ctx,
    ).where(PageVisit.content_id.isnot(None))
    row = ctx.session.execute(statement).first()
    return json_response(request, {
        'period_info': _period_info(request),
        'total_visits': row[0],
        'unique_visitors': row[1],
        'avg_time_spent': row[2],
    })


@router.api_route(
    '/page-visits/content_performance/', methods=list(_ACTION_GET_REST), include_in_schema=False
)
async def content_performance_rest(
    request: Request,
    ctx: Access = Depends(access(allow_any, authenticators=COOKIE_FIRST, allow=ACTION_GET_ALLOW)),
) -> Any:
    raise MethodNotAllowed(request.method)


@router.get('/page-visits/referrer_analysis/', status_code=200)
async def referrer_analysis(
    request: Request,
    ctx: Access = Depends(access(allow_any, authenticators=COOKIE_FIRST, allow=ACTION_GET_ALLOW)),
) -> Any:
    statement = _filter_statement(
        select(
            PageVisit.referrer,
            func.count(PageVisit.id).label('visit_count'),
            func.count(func.distinct(PageVisit.ip_address)).label('unique_visitors'),
        ),
        request,
        ctx,
    ).where(PageVisit.referrer.isnot(None)).where(PageVisit.referrer != '')
    statement = statement.group_by(PageVisit.referrer).order_by(func.count(PageVisit.id).desc())
    return json_response(request, {
        'period_info': _period_info(request),
        'referrers': [
            {'referrer': row[0], 'visit_count': row[1], 'unique_visitors': row[2]}
            for row in ctx.session.execute(statement)
        ],
    })


@router.api_route(
    '/page-visits/referrer_analysis/', methods=list(_ACTION_GET_REST), include_in_schema=False
)
async def referrer_analysis_rest(
    request: Request,
    ctx: Access = Depends(access(allow_any, authenticators=COOKIE_FIRST, allow=ACTION_GET_ALLOW)),
) -> Any:
    raise MethodNotAllowed(request.method)


def _page_visit(ctx: Access, pk: str) -> PageVisit:
    """Look one page visit up the way ``get_object_or_404`` does.

    A lookup that is not an integer never reaches the database - the baseline
    turns the cast failure into a bare 404 - while a well-formed miss keeps
    the untranslated English sentence Django builds for it.
    """
    try:
        ident = int(pk)
    except ValueError:
        raise NotFound()
    row = ctx.session.scalars(select(PageVisit).where(PageVisit.id == ident)).first()
    if row is None:
        raise NotFound('No PageVisit matches the given query.')
    return row


@router.get('/page-visits/{pk:nodot}/', status_code=200)
async def page_visits_detail(
    request: Request,
    pk: str,
    ctx: Access = Depends(access(is_admin_user, authenticators=COOKIE_FIRST, allow=PAGE_VISITS_DETAIL_ALLOW)),
) -> Any:
    return json_response(request, serialize_page_visit(_page_visit(ctx, pk)))


@router.api_route(
    '/page-visits/{pk:nodot}/', methods=['PUT', 'PATCH'], include_in_schema=False
)
async def page_visits_update(
    request: Request,
    pk: str,
    ctx: Access = Depends(access(is_admin_user, authenticators=COOKIE_FIRST, allow=PAGE_VISITS_DETAIL_ALLOW)),
) -> Any:
    """Answer a write the way the baseline does - by never performing one.

    The lookup still runs first, so a miss is a 404; on a hit the serializer
    dies validating the payload and no row is ever written.
    """
    _page_visit(ctx, pk)
    _build_serializer_fields()
    return json_response(request, None, status_code=200)


@router.delete('/page-visits/{pk:nodot}/', status_code=200)
async def page_visits_delete(
    request: Request,
    pk: str,
    ctx: Access = Depends(access(is_admin_user, authenticators=COOKIE_FIRST, allow=PAGE_VISITS_DETAIL_ALLOW)),
) -> Any:
    ctx.session.delete(_page_visit(ctx, pk))
    ctx.session.flush()
    return json_response(request, None, status_code=204)


@router.options('/page-visits/{pk:nodot}/', include_in_schema=False)
async def page_visits_detail_options(
    request: Request,
    pk: str,
    ctx: Access = Depends(access(is_admin_user, authenticators=COOKIE_FIRST, allow=PAGE_VISITS_DETAIL_ALLOW)),
) -> Any:
    """Describe the endpoint, or die describing the row that exists.

    The baseline swallows the 404 from the lookup and answers plain metadata;
    when the row is there it goes on to describe the writable fields and hits
    the serializer defect instead.
    """
    try:
        _page_visit(ctx, pk)
    except NotFound:
        return json_response(request, PAGE_VISIT_METADATA)
    _build_serializer_fields()
    return json_response(request, PAGE_VISIT_METADATA)


@router.api_route(
    '/page-visits/{pk:nodot}/', methods=list(_PAGE_VISITS_DETAIL_REST), include_in_schema=False
)
async def page_visits_detail_rest(
    request: Request,
    pk: str,
    ctx: Access = Depends(access(is_admin_user, authenticators=COOKIE_FIRST, allow=PAGE_VISITS_DETAIL_ALLOW)),
) -> Any:
    raise MethodNotAllowed(request.method)


add_head_to_get_routes(router)
