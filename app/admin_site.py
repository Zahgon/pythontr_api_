"""HTML administration site served at ``/admin/``.

The baseline ships a full server-rendered admin: an unauthenticated
``GET /admin/`` redirects to ``/admin/login/?next=/admin/`` which renders a
Turkish login page, and a signed-in staff member gets an index, a
changelist per registered model and an editable change form.

This module reproduces that surface with an ``APIRouter`` plus the
templates under ``app/templates/admin/``.  ``core.admin.REGISTRY`` supplies
the per-model column, filter and search metadata.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from string import Template
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Request
from sqlalchemy import func, or_, select
from starlette.responses import RedirectResponse, Response

from app import settings
from app.db import get_session
from app.security import constant_time_compare, get_random_string
from core import admin as admin_registry
from core.models import User

router = APIRouter()

TEMPLATE_DIR = Path(__file__).resolve().parent / 'templates' / 'admin'

SESSION_COOKIE = 'sessionid'
CSRF_COOKIE = 'csrftoken'
CSRF_FIELD = 'csrfmiddlewaretoken'
CSRF_SECRET_LENGTH = 32
CSRF_ALPHABET = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
SESSION_MAX_AGE = 1209600
CSRF_MAX_AGE = 31449600

HTML_TYPE = 'text/html; charset=utf-8'
CACHE_CONTROL = 'max-age=0, no-cache, no-store, must-revalidate, private'


def _load(name: str) -> Template:
    return Template((TEMPLATE_DIR / name).read_text(encoding='utf-8'))


BASE_TEMPLATE = _load('base.html')
LOGIN_TEMPLATE = _load('login.html')
INDEX_TEMPLATE = _load('index.html')
INDEX_APP_TEMPLATE = _load('index_app.html')
INDEX_ROW_TEMPLATE = _load('index_row.html')
CHANGELIST_TEMPLATE = _load('changelist.html')
CHANGELIST_ROW_TEMPLATE = _load('changelist_row.html')
CHANGELIST_FILTER_TEMPLATE = _load('changelist_filter.html')
CHANGE_FORM_TEMPLATE = _load('change_form.html')
CHANGE_FORM_ROW_TEMPLATE = _load('change_form_row.html')


def _escape(value: Any) -> str:
    text = '' if value is None else str(value)
    return (
        text.replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
        .replace("'", '&#x27;')
    )


def _http_date(moment: datetime) -> str:
    stamp = moment.astimezone(timezone.utc)
    days = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')
    months = (
        'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
        'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
    )
    return '%s, %02d %s %04d %02d:%02d:%02d GMT' % (
        days[stamp.weekday()],
        stamp.day,
        months[stamp.month - 1],
        stamp.year,
        stamp.hour,
        stamp.minute,
        stamp.second,
    )


def _admin_headers() -> Dict[str, str]:
    now = datetime.now(timezone.utc)
    return {
        'Cache-Control': CACHE_CONTROL,
        'Expires': _http_date(now),
        'Vary': 'Cookie',
    }


def _html(body: str, status_code: int = 200) -> Response:
    return Response(content=body, status_code=status_code, media_type=HTML_TYPE, headers=_admin_headers())


def _redirect(location: str) -> Response:
    response = RedirectResponse(url=location, status_code=302)
    for key, value in _admin_headers().items():
        response.headers[key] = value
    response.headers['content-type'] = HTML_TYPE
    return response


def _sign(payload: str) -> str:
    key = hashlib.sha256(('admin.session' + settings.SECRET_KEY).encode('utf-8')).digest()
    return hmac.new(key, payload.encode('utf-8'), hashlib.sha256).hexdigest()


def _make_session(user_id: int) -> str:
    payload = '%d:%d' % (user_id, int(time.time()))
    return '%s:%s' % (payload, _sign(payload))


def _read_session(raw: Optional[str]) -> Optional[int]:
    if not raw:
        return None
    parts = raw.rsplit(':', 1)
    if len(parts) != 2:
        return None
    payload, signature = parts
    if not constant_time_compare(signature, _sign(payload)):
        return None
    identifier = payload.split(':', 1)[0]
    try:
        return int(identifier)
    except ValueError:
        return None


def _current_staff(request: Request) -> Optional[User]:
    user_id = _read_session(request.cookies.get(SESSION_COOKIE))
    if user_id is None:
        return None
    session = get_session()
    user = session.scalars(select(User).where(User.id == user_id)).first()
    if user is None or not user.is_active or not user.is_staff:
        return None
    return user


def _login_redirect(next_url: str) -> Response:
    return _redirect('/admin/login/?next=%s' % next_url)


def _mask_csrf_secret(secret: str) -> str:
    # The cookie carries the bare 32-char secret while the form field carries a
    # 64-char masked pair: a fresh 32-char mask followed by the secret shifted
    # through it. Both halves are needed to unmask on POST.
    mask = get_random_string(CSRF_SECRET_LENGTH)
    size = len(CSRF_ALPHABET)
    shifted = ''.join(
        CSRF_ALPHABET[(CSRF_ALPHABET.index(pair[0]) + CSRF_ALPHABET.index(pair[1])) % size]
        for pair in zip(secret, mask)
    )
    return mask + shifted


def _unmask_csrf_token(token: str) -> str:
    if len(token) != CSRF_SECRET_LENGTH * 2:
        return token
    mask, shifted = token[:CSRF_SECRET_LENGTH], token[CSRF_SECRET_LENGTH:]
    size = len(CSRF_ALPHABET)
    return ''.join(
        CSRF_ALPHABET[(CSRF_ALPHABET.index(pair[0]) - CSRF_ALPHABET.index(pair[1])) % size]
        for pair in zip(shifted, mask)
    )


def _render_login(request: Request, errornote: str = '', status_code: int = 200) -> Response:
    next_url = request.query_params.get('next') or '/admin/'
    token = request.cookies.get(CSRF_COOKIE) or get_random_string(CSRF_SECRET_LENGTH)
    form_action = request.url.path
    if request.url.query:
        form_action = '%s?%s' % (form_action, request.url.query)
    body = LOGIN_TEMPLATE.substitute(
        errornote=errornote,
        csrf_token=_escape(_mask_csrf_secret(token)),
        next=_escape(next_url),
        form_action=_escape(form_action),
    )
    response = _html(body, status_code=status_code)
    expires = _http_date(datetime.now(timezone.utc) + timedelta(seconds=CSRF_MAX_AGE))
    response.headers.append(
        'Set-Cookie',
        '%s=%s; expires=%s; Max-Age=%d; Path=/; SameSite=Lax'
        % (CSRF_COOKIE, token, expires, CSRF_MAX_AGE),
    )
    return response


def _chrome(title: str, bodyclass: str, breadcrumbs: str, content: str, user: User) -> str:
    usertools = (
        '<div id="user-tools">%s <a href="/admin/logout/">Oturumu kapat</a></div>'
        % _escape(user.email)
    )
    return BASE_TEMPLATE.substitute(
        title=_escape(title),
        extrastyle='',
        bodyclass=bodyclass,
        usertools=usertools,
        breadcrumbs=breadcrumbs,
        content=content,
    )


def _value_of(row: object, field: str) -> str:
    return _escape(getattr(row, field, ''))


def _order_rows(entry: admin_registry.ModelAdmin, statement: Any) -> Any:
    for field in entry.ordering:
        descending = field.startswith('-')
        column = getattr(entry.model, field[1:] if descending else field, None)
        if column is not None:
            statement = statement.order_by(column.desc() if descending else column.asc())
    return statement


@router.get('/admin/', status_code=200)
async def admin_index(request: Request) -> Response:
    user = _current_staff(request)
    if user is None:
        return _login_redirect('/admin/')
    apps: List[str] = []
    for app_label, app_name, entries in admin_registry.grouped():
        rows = ''.join(
            INDEX_ROW_TEMPLATE.substitute(
                model_name=entry.model_name,
                admin_url='/admin/%s/%s/' % (entry.app_label, entry.model_name),
                verbose_name_plural=_escape(entry.verbose_name_plural),
                add_link=(
                    '<td><a href="/admin/%s/%s/add/" class="addlink">Ekle</a></td>'
                    % (entry.app_label, entry.model_name)
                    if entry.has_add_permission()
                    else '<td>&nbsp;</td>'
                ),
            )
            for entry in entries
        )
        apps.append(
            INDEX_APP_TEMPLATE.substitute(
                app_label=app_label,
                app_name=_escape(app_name),
                rows=rows,
            )
        )
    content = INDEX_TEMPLATE.substitute(app_list=''.join(apps))
    breadcrumbs = ''
    return _html(_chrome('Site yönetimi', ' dashboard', breadcrumbs, content, user))


@router.get('/admin/login/', status_code=200)
async def admin_login_form(request: Request) -> Response:
    return _render_login(request)


@router.post('/admin/login/', status_code=200)
async def admin_login_submit(request: Request) -> Response:
    form = await request.form()
    email = str(form.get('username') or '')
    password = str(form.get('password') or '')
    next_url = str(form.get('next') or '/admin/')
    submitted = _unmask_csrf_token(str(form.get(CSRF_FIELD) or ''))
    expected = request.cookies.get(CSRF_COOKIE) or ''
    if not expected or not constant_time_compare(submitted, expected):
        return _html('CSRF doğrulaması başarısız oldu. İstek iptal edildi.', status_code=403)
    session = get_session()
    user = session.scalars(select(User).where(User.email == email)).first()
    if user is None or not user.check_password(password) or not user.is_active or not user.is_staff:
        note = (
            '<p class="errornote">Lütfen bir personel hesabı için doğru '
            'Email ve parola giriniz. Her iki alan da büyük küçük harfe '
            'duyarlı olabilir.</p>'
        )
        return _render_login(request, errornote=note, status_code=200)
    response = _redirect(next_url or '/admin/')
    response.headers.append(
        'Set-Cookie',
        '%s=%s; Max-Age=%d; Path=/; SameSite=Lax; HttpOnly'
        % (SESSION_COOKIE, quote(_make_session(user.id)), SESSION_MAX_AGE),
    )
    return response


@router.get('/admin/logout/', status_code=200)
async def admin_logout(request: Request) -> Response:
    response = _redirect('/admin/login/?next=/admin/')
    response.headers.append(
        'Set-Cookie',
        '%s=; Max-Age=0; Path=/; SameSite=Lax; HttpOnly' % SESSION_COOKIE,
    )
    return response


@router.get('/admin/{app_label}/{model_name}/', status_code=200)
async def admin_changelist(request: Request, app_label: str, model_name: str) -> Response:
    user = _current_staff(request)
    path = '/admin/%s/%s/' % (app_label, model_name)
    if user is None:
        return _login_redirect(path)
    entry = admin_registry.find(app_label, model_name)
    if entry is None:
        request.scope.pop('allow_methods', None)
        return Response(status_code=404)

    session = get_session()
    statement = select(entry.model)
    query = request.query_params.get('q') or ''
    if query and entry.search_fields:
        clauses = [
            getattr(entry.model, field).ilike('%%%s%%' % query)
            for field in entry.search_fields
            if getattr(entry.model, field, None) is not None
        ]
        if clauses:
            statement = statement.where(or_(*clauses))
    filtered = ''
    for field in entry.list_filter:
        raw = request.query_params.get(field)
        column = getattr(entry.model, field, None)
        if raw is None or column is None:
            continue
        if raw in ('True', 'False'):
            statement = statement.where(column.is_(raw == 'True'))
        else:
            statement = statement.where(column == raw)
        filtered = ' filtered'

    total = session.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
    rows_data = list(session.scalars(_order_rows(entry, statement)).unique())

    headers = ''.join(
        '<th scope="col"><div class="text"><span>%s</span></div></th>' % _escape(field)
        for field in entry.list_display
    )
    rendered_rows: List[str] = []
    for index, row in enumerate(rows_data):
        first_field = entry.list_display[0]
        cells = ''.join(
            '<td class="field-%s">%s</td>' % (_escape(field), _value_of(row, field))
            for field in entry.list_display[1:]
        )
        rendered_rows.append(
            CHANGELIST_ROW_TEMPLATE.substitute(
                parity='row1' if index % 2 == 0 else 'row2',
                first_field=_escape(first_field),
                change_url='%s%s/change/' % (path, getattr(row, 'id', '')),
                first_value=_value_of(row, first_field),
                cells=cells,
            )
        )

    blocks = ''.join(
        '<h3>%s</h3><ul><li><a href="?%s=True">Evet</a></li>'
        '<li><a href="?%s=False">Hayır</a></li></ul>'
        % (_escape(field), _escape(field), _escape(field))
        for field in entry.list_filter
    )
    filters = CHANGELIST_FILTER_TEMPLATE.substitute(blocks=blocks) if blocks else ''

    content = CHANGELIST_TEMPLATE.substitute(
        filtered=filtered,
        query=_escape(query),
        result_count=total,
        csrf_token=_escape(request.cookies.get(CSRF_COOKIE) or ''),
        headers=headers,
        rows=''.join(rendered_rows),
        verbose_name_plural=_escape(entry.verbose_name_plural),
        filters=filters,
    )
    breadcrumbs = (
        '<div class="breadcrumbs"><a href="/admin/">Ana sayfa</a> &rsaquo; '
        '%s</div>' % _escape(entry.verbose_name_plural)
    )
    return _html(_chrome(entry.verbose_name_plural, ' app-%s model-%s change-list' % (app_label, model_name), breadcrumbs, content, user))


def _render_change_form(
    request: Request,
    user: User,
    entry: admin_registry.ModelAdmin,
    row: Optional[object],
    action: str,
    errornote: str = '',
) -> Response:
    rows = ''
    for field in entry.editable_fields:
        current = getattr(row, field, '') if row is not None else ''
        column = getattr(entry.model, field, None)
        python_type = getattr(getattr(column, 'type', None), 'python_type', None)
        is_boolean = python_type is bool if python_type is not None else isinstance(current, bool)
        if is_boolean:
            widget = (
                '<input type="checkbox" name="%s" id="id_%s"%s>'
                % (_escape(field), _escape(field), ' checked' if current else '')
            )
        else:
            widget = (
                '<input type="text" name="%s" id="id_%s" value="%s">'
                % (_escape(field), _escape(field), _escape(current))
            )
        rows += CHANGE_FORM_ROW_TEMPLATE.substitute(
            name=_escape(field),
            required_class='',
            label=_escape(field),
            widget=widget,
        )
    content = CHANGE_FORM_TEMPLATE.substitute(
        errornote=errornote,
        action=action,
        form_id='%s_form' % entry.model_name,
        csrf_token=_escape(request.cookies.get(CSRF_COOKIE) or ''),
        verbose_name=_escape(entry.verbose_name),
        rows=rows,
    )
    breadcrumbs = (
        '<div class="breadcrumbs"><a href="/admin/">Ana sayfa</a> &rsaquo; '
        '<a href="/admin/%s/%s/">%s</a></div>'
        % (entry.app_label, entry.model_name, _escape(entry.verbose_name_plural))
    )
    bodyclass = ' app-%s model-%s change-form' % (entry.app_label, entry.model_name)
    return _html(_chrome(entry.verbose_name, bodyclass, breadcrumbs, content, user))


def _apply_form(entry: admin_registry.ModelAdmin, row: object, form: Any) -> None:
    for field in entry.editable_fields:
        column = getattr(entry.model, field, None)
        python_type = getattr(getattr(column, 'type', None), 'python_type', None)
        if python_type is bool:
            setattr(row, field, field in form)
        elif field in form:
            setattr(row, field, str(form.get(field) or ''))


@router.get('/admin/{app_label}/{model_name}/add/', status_code=200)
async def admin_add_form(request: Request, app_label: str, model_name: str) -> Response:
    user = _current_staff(request)
    path = '/admin/%s/%s/add/' % (app_label, model_name)
    if user is None:
        return _login_redirect(path)
    entry = admin_registry.find(app_label, model_name)
    if entry is None or not entry.has_add_permission():
        request.scope.pop('allow_methods', None)
        return Response(status_code=404)
    return _render_change_form(request, user, entry, None, path)


@router.post('/admin/{app_label}/{model_name}/add/', status_code=200)
async def admin_add_submit(request: Request, app_label: str, model_name: str) -> Response:
    user = _current_staff(request)
    path = '/admin/%s/%s/add/' % (app_label, model_name)
    if user is None:
        return _login_redirect(path)
    entry = admin_registry.find(app_label, model_name)
    if entry is None or not entry.has_add_permission():
        request.scope.pop('allow_methods', None)
        return Response(status_code=404)
    session = get_session()
    row = entry.model()
    _apply_form(entry, row, await request.form())
    saver = getattr(row, 'save', None)
    if callable(saver):
        saver(session)
    else:
        session.add(row)
        session.flush()
    session.commit()
    return _redirect('/admin/%s/%s/' % (app_label, model_name))


@router.get('/admin/{app_label}/{model_name}/{pk}/change/', status_code=200)
async def admin_change_form(request: Request, app_label: str, model_name: str, pk: int) -> Response:
    user = _current_staff(request)
    path = '/admin/%s/%s/%s/change/' % (app_label, model_name, pk)
    if user is None:
        return _login_redirect(path)
    entry = admin_registry.find(app_label, model_name)
    if entry is None:
        request.scope.pop('allow_methods', None)
        return Response(status_code=404)
    session = get_session()
    row = session.scalars(select(entry.model).where(entry.model.id == pk)).first()
    if row is None:
        request.scope.pop('allow_methods', None)
        return Response(status_code=404)
    return _render_change_form(request, user, entry, row, path)


@router.post('/admin/{app_label}/{model_name}/{pk}/change/', status_code=200)
async def admin_change_submit(request: Request, app_label: str, model_name: str, pk: int) -> Response:
    user = _current_staff(request)
    path = '/admin/%s/%s/%s/change/' % (app_label, model_name, pk)
    if user is None:
        return _login_redirect(path)
    entry = admin_registry.find(app_label, model_name)
    if entry is None:
        request.scope.pop('allow_methods', None)
        return Response(status_code=404)
    session = get_session()
    row = session.scalars(select(entry.model).where(entry.model.id == pk)).first()
    if row is None:
        request.scope.pop('allow_methods', None)
        return Response(status_code=404)
    _apply_form(entry, row, await request.form())
    saver = getattr(row, 'save', None)
    if callable(saver):
        saver(session)
    else:
        session.add(row)
        session.flush()
    session.commit()
    return _redirect('/admin/%s/%s/' % (app_label, model_name))
