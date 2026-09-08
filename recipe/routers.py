"""HTTP routing for the recipe application.

Every collection is exposed through its own :class:`fastapi.APIRouter` mounted
under a literal prefix, so the full route inventory is statically visible.

Dispatch order matters and is reproduced deliberately.  The baseline resolves
credentials and permissions *before* it resolves the HTTP method, so an
anonymous request that uses an unsupported method is rejected as unauthorised
rather than as a bad method.  Each path therefore registers:

* real method decorators for the actions it supports, each declaring the
  permission that action requires;
* one catch-all route covering the remaining methods under the collection's
  default permission, which authenticates first and only then reports that the
  method is not allowed.

``access(..., allow=...)`` records the advertised method list on the request
before authenticating, so the ``Allow`` header is present on every response,
including the rejections.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, or_, select

from app import parsing
from app.deps import (
    Access,
    access,
    allow_any,
    check_object_permission,
    is_admin_user,
    is_authenticated,
    is_authenticated_or_read_only,
)
from app.i18n import gettext as _
from app.urls import suffixed
from app.wire import JSONResponse, MethodNotAllowed, NotFound, json_response, paginate
from core.models import (
    ARTICLE_CONTENT_TYPE_ID,
    COMMENT_CONTENT_TYPE_ID,
    Article,
    Category,
    Comment,
    ContentType,
    Message,
    Slider,
    core_article_categories,
)
from recipe import schemas
from recipe.permissions import (
    is_authenticated_and_owner,
    is_authenticated_and_owner_or_admin,
)

LIST_ALLOW = ('GET', 'POST', 'HEAD', 'OPTIONS')
DETAIL_ALLOW = ('GET', 'PUT', 'PATCH', 'HEAD', 'OPTIONS')
ARTICLE_DETAIL_ALLOW = ('GET', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS')
ROOT_ALLOW = ('GET', 'HEAD', 'OPTIONS')

_LIST_REST = ('PUT', 'PATCH', 'DELETE', 'OPTIONS')
_DETAIL_REST = ('POST', 'DELETE', 'OPTIONS')
_ARTICLE_DETAIL_REST = ('POST', 'OPTIONS')
_ROOT_REST = ('POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS')

router = APIRouter()

categories_router = APIRouter(prefix='/categories')
articles_router = APIRouter(prefix='/articles')
sliders_router = APIRouter(prefix='/sliders')
comments_router = APIRouter(prefix='/comments')
messages_router = APIRouter(prefix='/messages')


def listing(request: Request, rows: List[Dict[str, Any]]) -> Any:
    """Wrap a serialised list in the pagination envelope when paging is on."""
    payload = paginate(request, rows)
    if payload.pop('unpaginated', False):
        return payload['results']
    return payload


def _query_param(request: Request, name: str) -> Optional[str]:
    value = request.query_params.get(name)
    if value is None or value == '':
        return None
    return value


def _user_pk(user: object) -> int:
    """Return the primary key the ``me`` filters compare against.

    The baseline puts the request user straight into the filter, so an
    anonymous caller reaches the database layer as a non-row and the query
    raises. Returning ``None`` here instead would quietly produce an empty
    result and a 404 where the baseline answers 500.
    """
    pk = getattr(user, 'id', None)
    if pk is None:
        raise TypeError(
            "Field 'id' expected a number but got <SimpleLazyObject: AnonymousUser>."
        )
    return int(pk)


def _mapped_attr(row: object, field: str) -> str:
    """Translate an input field name to the attribute that holds its value.

    The write schemas name a foreign key the way the baseline's serializers
    did -- ``parent_category``, ``approval_user`` -- while the model exposes
    the relationship under that name and the identifier under ``<name>_id``.
    Reading the relationship yields a row object where an identifier is
    expected, and writing an identifier onto it assigns an int where a row is
    expected, so both directions go through the column.
    """
    column = '%s_id' % field
    return column if hasattr(row, column) else field


def _apply_supplied(row: object, payload: Any, supplied: Iterable[str]) -> None:
    """Assign only the fields the request body actually carried.

    The baseline's serializers build ``validated_data`` from the keys present
    in the request, so a field that was not sent stays untouched and a field
    sent as ``null`` is written as NULL. Dumping the whole schema and dropping
    the Nones collapses those two cases into one and loses the explicit null.
    """
    supplied = set(supplied)
    dumped = payload.model_dump()
    for field, value in dumped.items():
        if field in supplied:
            setattr(row, _mapped_attr(row, field), value)


def _method_not_allowed(request: Request) -> None:
    raise MethodNotAllowed(request.method)


# ---------------------------------------------------------------------------
# API root
# ---------------------------------------------------------------------------


@router.get('/', status_code=200)
async def api_root(request: Request, ctx: Access = Depends(access(allow_any, allow=ROOT_ALLOW))) -> JSONResponse:
    """The router index document, listing every registered collection."""
    base = str(request.base_url).rstrip('/')
    suffix = request.scope.get('format_suffix')
    payload = {
        name: suffixed(base + '/api/recipe/' + name + '/', suffix)
        for name in ('categories', 'articles', 'sliders', 'comments',
                     'messages')
    }
    return json_response(request, payload, status_code=200)


@router.api_route('/', methods=list(_ROOT_REST), status_code=405)
async def api_root_other(
    request: Request, ctx: Access = Depends(access(allow_any, allow=ROOT_ALLOW))
) -> JSONResponse:
    _method_not_allowed(request)


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


def _category_queryset(ctx: Access) -> List[Category]:
    statement = select(Category)
    search = _query_param(ctx.request, 'search')
    if search is not None:
        statement = statement.where(Category.name.ilike('%{}%'.format(search)))
    rows = list(ctx.session.scalars(statement).unique())
    return sorted(rows, key=lambda item: item.full_category_name)


def _category_object(ctx: Access, pk: str) -> Category:
    """Resolve by primary key when numeric, otherwise by slug.

    The lookup is unguarded on purpose: a miss raises, which the baseline
    surfaces as a server error rather than a 404.
    """
    if pk.isdigit():
        statement = select(Category).where(Category.id == int(pk))
    else:
        statement = select(Category).where(Category.slug == pk)
    row = ctx.session.scalars(statement).first()
    if row is None:
        raise Category.DoesNotExist('Category matching query does not exist.')
    return row


@categories_router.get('/', status_code=200)
async def category_list(
    request: Request,
    ctx: Access = Depends(access(is_authenticated_or_read_only, allow=LIST_ALLOW)),
) -> JSONResponse:
    rows = [schemas.serialize_category(item) for item in _category_queryset(ctx)]
    return json_response(request, listing(request, rows), status_code=200)


@categories_router.post('/', status_code=201)
async def category_create(
    request: Request, ctx: Access = Depends(access(is_admin_user, allow=LIST_ALLOW))
) -> JSONResponse:
    data = await parsing.parse_body(request)
    payload = parsing.validate(schemas.CategoryInput, data, schemas.CATEGORY_INPUT_ORDER)
    row = Category(**payload.model_dump(exclude_none=True))
    row.user = ctx.user
    ctx.session.add(row)
    row.save(ctx.session)
    ctx.session.commit()
    return json_response(request, schemas.serialize_category(row), status_code=201)


@categories_router.api_route('/', methods=list(_LIST_REST), status_code=405)
async def category_list_other(
    request: Request, ctx: Access = Depends(access(is_authenticated, allow=LIST_ALLOW))
) -> JSONResponse:
    _method_not_allowed(request)


@categories_router.get('/{pk:nodot}/', status_code=200)
async def category_detail(
    request: Request,
    pk: str,
    ctx: Access = Depends(access(is_authenticated_or_read_only, allow=DETAIL_ALLOW)),
) -> JSONResponse:
    row = _category_object(ctx, pk)
    return json_response(request, schemas.serialize_category(row), status_code=200)


@categories_router.put('/{pk:nodot}/', status_code=200)
async def category_update(
    request: Request, pk: str, ctx: Access = Depends(access(is_authenticated, allow=DETAIL_ALLOW))
) -> JSONResponse:
    return await _category_write(request, pk, ctx, partial=False)


@categories_router.patch('/{pk:nodot}/', status_code=200)
async def category_partial_update(
    request: Request, pk: str, ctx: Access = Depends(access(is_authenticated, allow=DETAIL_ALLOW))
) -> JSONResponse:
    return await _category_write(request, pk, ctx, partial=True)


async def _category_write(request: Request, pk: str, ctx: Access, partial: bool) -> JSONResponse:
    row = _category_object(ctx, pk)
    data = await parsing.parse_body(request)
    supplied = set(data) if isinstance(data, dict) else set()
    if partial:
        merged = {field: getattr(row, _mapped_attr(row, field))
                  for field in schemas.CATEGORY_INPUT_ORDER}
        merged.update(data)
        data = merged
    payload = parsing.validate(schemas.CategoryInput, data, schemas.CATEGORY_INPUT_ORDER)
    _apply_supplied(row, payload, supplied)
    row.save(ctx.session)
    ctx.session.commit()
    if 'parent_category' in supplied:
        ctx.session.expire(row, ['parent_category'])
    return json_response(request, schemas.serialize_category(row), status_code=200)


@categories_router.api_route('/{pk:nodot}/', methods=list(_DETAIL_REST), status_code=405)
async def category_detail_other(
    request: Request, pk: str, ctx: Access = Depends(access(is_authenticated, allow=DETAIL_ALLOW))
) -> JSONResponse:
    _method_not_allowed(request)


# ---------------------------------------------------------------------------
# Articles
# ---------------------------------------------------------------------------


def _article_queryset(ctx: Access) -> List[Article]:
    request = ctx.request
    statement = select(Article)
    search = _query_param(request, 'search')
    if search is not None:
        statement = statement.where(Article.title.ilike('%{}%'.format(search)))

    categories = [value for value in request.query_params.getlist('category') if value]
    if categories:
        statement = statement.join(
            core_article_categories, core_article_categories.c.article_id == Article.id
        ).where(core_article_categories.c.category_id.in_([int(value) for value in categories]))

    me = _query_param(request, 'me')
    is_active = _query_param(request, 'is_active')
    if me is not None:
        statement = statement.where(Article.user_id == _user_pk(ctx.user))
        if is_active in ('true', 'false'):
            statement = statement.where(Article.is_active.is_(is_active == 'true'))
    else:
        statement = statement.where(Article.is_active.is_(True))

    statement = statement.order_by(Article.id.desc()).distinct()
    rows = list(ctx.session.scalars(statement).unique())
    if not rows:
        raise NotFound(_('not_found'))
    return rows


def _article_object(ctx: Access, pk: str) -> Article:
    if pk.isdigit():
        statement = select(Article).where(Article.id == int(pk))
    else:
        statement = select(Article).where(Article.slug == pk)
    row = ctx.session.scalars(statement).first()
    if row is None:
        raise Article.DoesNotExist('Article matching query does not exist.')
    return row


@articles_router.get('/', status_code=200)
async def article_list(
    request: Request,
    ctx: Access = Depends(access(is_authenticated_or_read_only, allow=LIST_ALLOW)),
) -> JSONResponse:
    rows = [schemas.serialize_article_list(item) for item in _article_queryset(ctx)]
    return json_response(request, listing(request, rows), status_code=200)


@articles_router.post('/', status_code=201)
async def article_create(
    request: Request, ctx: Access = Depends(access(is_authenticated, allow=LIST_ALLOW))
) -> JSONResponse:
    data = await parsing.parse_body(request)
    if parsing.is_form_request(request) and 'categories' not in data:
        data['categories'] = []
    payload = parsing.validate(schemas.ArticleInput, data, schemas.ARTICLE_INPUT_ORDER)
    fields = payload.model_dump(exclude_none=True)
    category_ids = fields.pop('categories', [])
    is_approval = fields.pop('is_approval', None)
    row = Article(**fields)
    row.user = ctx.user
    if is_approval is not None:
        _apply_approval(ctx, row, is_approval)
    row.categories = list(
        ctx.session.scalars(select(Category).where(Category.id.in_(category_ids))).unique()
    )
    ctx.session.add(row)
    row.save(ctx.session)
    ctx.session.commit()
    return json_response(request, schemas.serialize_article(row, ctx.session), status_code=201)


def _apply_approval(ctx: Access, row: Article, value: bool) -> None:
    """Only staff may raise the approval flag; the reviewer is recorded."""
    if value and not ctx.is_staff:
        from app.wire import ValidationFailed

        raise ValidationFailed(
            {'is_approval': 'Onay durumunu sadece yöneticiler değiştirebilir.'}
        )
    row.is_approval = value
    row.approval_user = ctx.user if value else None


@articles_router.api_route('/', methods=list(_LIST_REST), status_code=405)
async def article_list_other(
    request: Request, ctx: Access = Depends(access(is_authenticated, allow=LIST_ALLOW))
) -> JSONResponse:
    _method_not_allowed(request)


@articles_router.get('/{pk:nodot}/', status_code=200)
async def article_detail(
    request: Request,
    pk: str,
    ctx: Access = Depends(access(is_authenticated_or_read_only, allow=ARTICLE_DETAIL_ALLOW)),
) -> JSONResponse:
    row = _article_object(ctx, pk)
    return json_response(request, schemas.serialize_article(row, ctx.session), status_code=200)


@articles_router.put('/{pk:nodot}/', status_code=200)
async def article_update(
    request: Request,
    pk: str,
    ctx: Access = Depends(access(is_authenticated, allow=ARTICLE_DETAIL_ALLOW)),
) -> JSONResponse:
    return await _article_write(request, pk, ctx, partial=False)


@articles_router.patch('/{pk:nodot}/', status_code=200)
async def article_partial_update(
    request: Request,
    pk: str,
    ctx: Access = Depends(access(is_authenticated, allow=ARTICLE_DETAIL_ALLOW)),
) -> JSONResponse:
    return await _article_write(request, pk, ctx, partial=True)


async def _article_write(request: Request, pk: str, ctx: Access, partial: bool) -> JSONResponse:
    row = _article_object(ctx, pk)
    data = await parsing.parse_body(request)
    if partial:
        merged: Dict[str, Any] = {
            'categories': [item.id for item in row.categories],
            'title': row.title,
            'title_h1': row.title_h1,
            'description': row.description,
            'content': row.content,
        }
        merged.update(data)
        data = merged
    payload = parsing.validate(schemas.ArticleInput, data, schemas.ARTICLE_INPUT_ORDER)
    fields = payload.model_dump(exclude_none=True)
    category_ids = fields.pop('categories', None)
    is_approval = fields.pop('is_approval', None)
    for field, value in fields.items():
        setattr(row, field, value)
    if is_approval is not None:
        _apply_approval(ctx, row, is_approval)
    if category_ids:
        row.categories = list(
            ctx.session.scalars(select(Category).where(Category.id.in_(category_ids))).unique()
        )
    row.save(ctx.session)
    ctx.session.commit()
    return json_response(request, schemas.serialize_article(row, ctx.session), status_code=200)


@articles_router.delete('/{pk:nodot}/', status_code=204)
async def article_destroy(
    request: Request,
    pk: str,
    ctx: Access = Depends(access(allow_any, allow=ARTICLE_DETAIL_ALLOW)),
) -> JSONResponse:
    row = _article_object(ctx, pk)
    row.is_delete = True
    ctx.session.add(row)
    ctx.session.commit()
    return json_response(request, None, status_code=204)


@articles_router.api_route('/{pk:nodot}/', methods=list(_ARTICLE_DETAIL_REST), status_code=405)
async def article_detail_other(
    request: Request,
    pk: str,
    ctx: Access = Depends(access(is_authenticated, allow=ARTICLE_DETAIL_ALLOW)),
) -> JSONResponse:
    _method_not_allowed(request)


# ---------------------------------------------------------------------------
# Sliders
# ---------------------------------------------------------------------------


def _slider_queryset(ctx: Access) -> List[Slider]:
    request = ctx.request
    statement = select(Slider).where(Slider.is_active.is_(True), Slider.is_delete.is_(False))
    search = _query_param(request, 'search')
    if search is not None:
        statement = statement.where(Slider.title.ilike('%{}%'.format(search)))
    if _query_param(request, 'me') is not None:
        statement = statement.where(Slider.user_id == ctx.user.id)
    statement = statement.order_by(Slider.id.desc()).distinct()
    rows = list(ctx.session.scalars(statement).unique())
    if not rows:
        raise NotFound(_('not_found'))
    return rows


def _slider_object(ctx: Access, pk: str) -> Slider:
    row = ctx.session.scalars(select(Slider).where(Slider.id == int(pk))).first()
    if row is None:
        raise Slider.DoesNotExist('Slider matching query does not exist.')
    return row


@sliders_router.get('/', status_code=200)
async def slider_list(
    request: Request,
    ctx: Access = Depends(access(is_authenticated_or_read_only, allow=LIST_ALLOW)),
) -> JSONResponse:
    rows = [schemas.serialize_slider(item) for item in _slider_queryset(ctx)]
    return json_response(request, listing(request, rows), status_code=200)


@sliders_router.post('/', status_code=201)
async def slider_create(
    request: Request, ctx: Access = Depends(access(is_authenticated, allow=LIST_ALLOW))
) -> JSONResponse:
    data = await parsing.parse_body(request)
    payload = parsing.validate(schemas.SliderInput, data, schemas.SLIDER_INPUT_ORDER)
    row = Slider(**payload.model_dump(exclude_none=True))
    row.user = ctx.user
    ctx.session.add(row)
    row.save(ctx.session)
    ctx.session.commit()
    return json_response(request, schemas.serialize_slider(row), status_code=201)


@sliders_router.api_route('/', methods=list(_LIST_REST), status_code=405)
async def slider_list_other(
    request: Request, ctx: Access = Depends(access(is_authenticated, allow=LIST_ALLOW))
) -> JSONResponse:
    _method_not_allowed(request)


@sliders_router.get('/{pk:nodot}/', status_code=200)
async def slider_detail(
    request: Request,
    pk: str,
    ctx: Access = Depends(access(is_authenticated_or_read_only, allow=DETAIL_ALLOW)),
) -> JSONResponse:
    row = _slider_object(ctx, pk)
    return json_response(request, schemas.serialize_slider(row), status_code=200)


@sliders_router.put('/{pk:nodot}/', status_code=200)
async def slider_update(
    request: Request, pk: str, ctx: Access = Depends(access(is_authenticated, allow=DETAIL_ALLOW))
) -> JSONResponse:
    return await _slider_write(request, pk, ctx, partial=False)


@sliders_router.patch('/{pk:nodot}/', status_code=200)
async def slider_partial_update(
    request: Request, pk: str, ctx: Access = Depends(access(is_authenticated, allow=DETAIL_ALLOW))
) -> JSONResponse:
    return await _slider_write(request, pk, ctx, partial=True)


async def _slider_write(request: Request, pk: str, ctx: Access, partial: bool) -> JSONResponse:
    row = _slider_object(ctx, pk)
    data = await parsing.parse_body(request)
    supplied = set(data) if isinstance(data, dict) else set()
    if partial:
        merged = {field: getattr(row, _mapped_attr(row, field))
                  for field in schemas.SLIDER_INPUT_ORDER}
        merged.update(data)
        data = merged
    payload = parsing.validate(schemas.SliderInput, data, schemas.SLIDER_INPUT_ORDER)
    _apply_supplied(row, payload, supplied)
    row.save(ctx.session)
    ctx.session.commit()
    return json_response(request, schemas.serialize_slider(row), status_code=200)


@sliders_router.api_route('/{pk:nodot}/', methods=list(_DETAIL_REST), status_code=405)
async def slider_detail_other(
    request: Request, pk: str, ctx: Access = Depends(access(is_authenticated, allow=DETAIL_ALLOW))
) -> JSONResponse:
    _method_not_allowed(request)


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------


def _comment_queryset(ctx: Access) -> List[Comment]:
    request = ctx.request
    statement = select(Comment).where(Comment.is_active.is_(True), Comment.is_delete.is_(False))
    comment_type = request.query_params.get('comment_type', 'article')
    if comment_type == 'article':
        visible = select(Article.id).where(
            Article.is_active.is_(True), Article.is_delete.is_(False)
        )
        statement = statement.where(
            Comment.content_type_id == ARTICLE_CONTENT_TYPE_ID,
            Comment.object_id.in_(visible),
        )
    elif comment_type == 'comment':
        statement = statement.where(Comment.content_type_id == COMMENT_CONTENT_TYPE_ID)
        parent_id = _query_param(request, 'parent_id')
        if parent_id is not None:
            statement = statement.where(Comment.object_id == int(parent_id))
    search = _query_param(request, 'search')
    if search is not None:
        statement = statement.where(Comment.name.ilike('%{}%'.format(search)))
    statement = statement.order_by(Comment.id.desc())
    return list(ctx.session.scalars(statement).unique())


@comments_router.get('/', status_code=200)
async def comment_list(
    request: Request, ctx: Access = Depends(access(allow_any, allow=LIST_ALLOW))
) -> JSONResponse:
    rows = [schemas.serialize_comment(item, ctx.session) for item in _comment_queryset(ctx)]
    return json_response(request, listing(request, rows), status_code=200)


def _comment_payload(ctx: Access, data: Dict[str, Any]) -> schemas.CommentInput:
    """Validate a comment write the way the baseline's serializer does.

    The baseline declares the captcha field on ``CommentSerializer`` itself and
    appends it to the end of ``Meta.fields``, so a missing captcha is collected
    alongside the field errors in one pass and reported after them.  The
    ``content_type`` relation is a primary key field whose queryset is checked
    in that same pass, so an unknown id is reported together with the captcha
    rather than reaching the database as a foreign key violation.
    """
    from app.wire import ValidationFailed
    from user.schemas import captcha_errors

    captcha: Dict[str, Any] = dict(captcha_errors(data) or {})
    try:
        payload = parsing.validate(schemas.CommentInput, data, schemas.COMMENT_INPUT_ORDER)
    except ValidationFailed as exc:
        errors = dict(exc.detail)
        errors.update(captcha)
        raise ValidationFailed(
            parsing.ordered_errors(errors, schemas.COMMENT_INPUT_ORDER)
        ) from None

    errors = {}
    if ctx.session.get(ContentType, payload.content_type) is None:
        message = _('Invalid pk "{pk_value}" - object does not exist.')
        errors['content_type'] = [message.format(pk_value=payload.content_type)]
    errors.update(captcha)
    if errors:
        raise ValidationFailed(parsing.ordered_errors(errors, schemas.COMMENT_INPUT_ORDER))
    return payload


@comments_router.post('/', status_code=201)
async def comment_create(
    request: Request, ctx: Access = Depends(access(allow_any, allow=LIST_ALLOW))
) -> JSONResponse:
    data = await parsing.parse_body(request)
    payload = _comment_payload(ctx, data)
    fields = payload.model_dump()
    fields['content_type_id'] = fields.pop('content_type')
    fields.pop('user', None)
    from user.schemas import CAPTCHA_REQUIRED

    if CAPTCHA_REQUIRED and data.get('captcha'):
        # ``CommentSerializer`` declares ``captcha`` as a writable field but
        # never removes it from ``validated_data``, so once a captcha actually
        # verifies the baseline hands an unknown attribute to the model
        # constructor and the request fails.  Reproduced rather than corrected:
        # the wire contract of a successful captcha is a 500.
        fields['captcha'] = data['captcha']
    row = Comment(**{key: value for key, value in fields.items() if value is not None})
    if ctx.is_authenticated:
        row.user = ctx.user
    ctx.session.add(row)
    ctx.session.flush()
    ctx.session.commit()
    return json_response(request, schemas.serialize_comment(row, ctx.session), status_code=201)


@comments_router.api_route('/', methods=list(_LIST_REST), status_code=405)
async def comment_list_other(
    request: Request, ctx: Access = Depends(access(is_authenticated, allow=LIST_ALLOW))
) -> JSONResponse:
    _method_not_allowed(request)


@comments_router.get('/{pk:nodot}/', status_code=200)
async def comment_detail(
    request: Request, pk: int, ctx: Access = Depends(access(is_authenticated, allow=DETAIL_ALLOW))
) -> JSONResponse:
    row = _comment_object(ctx, pk)
    return json_response(request, schemas.serialize_comment(row, ctx.session), status_code=200)


def _comment_object(ctx: Access, pk: int) -> Comment:
    row = ctx.session.get(Comment, pk)
    if row is None:
        raise NotFound()
    check_object_permission(ctx, row)
    return row


@comments_router.put('/{pk:nodot}/', status_code=200)
async def comment_update(
    request: Request, pk: int, ctx: Access = Depends(access(is_authenticated, allow=DETAIL_ALLOW))
) -> JSONResponse:
    return await _comment_write(request, pk, ctx, partial=False)


@comments_router.patch('/{pk:nodot}/', status_code=200)
async def comment_partial_update(
    request: Request, pk: int, ctx: Access = Depends(access(is_authenticated, allow=DETAIL_ALLOW))
) -> JSONResponse:
    return await _comment_write(request, pk, ctx, partial=True)


async def _comment_write(request: Request, pk: int, ctx: Access, partial: bool) -> JSONResponse:
    row = ctx.session.get(Comment, pk)
    if row is None:
        raise NotFound()
    if not is_authenticated_and_owner(ctx, row):
        from app.wire import PermissionDenied

        raise PermissionDenied()
    data = await parsing.parse_body(request)
    if partial:
        merged = {
            'content': row.content,
            'email': row.email,
            'name': row.name,
            'ip': row.ip,
            'content_type': row.content_type_id,
            'object_id': row.object_id,
        }
        merged.update(data)
        data = merged
    payload = _comment_payload(ctx, data)
    fields = payload.model_dump()
    fields['content_type_id'] = fields.pop('content_type')
    fields.pop('user', None)
    for field, value in fields.items():
        if value is not None:
            setattr(row, field, value)
    ctx.session.add(row)
    ctx.session.commit()
    return json_response(request, schemas.serialize_comment(row, ctx.session), status_code=200)


@comments_router.api_route('/{pk:nodot}/', methods=list(_DETAIL_REST), status_code=405)
async def comment_detail_other(
    request: Request, pk: int, ctx: Access = Depends(access(is_authenticated, allow=DETAIL_ALLOW))
) -> JSONResponse:
    _method_not_allowed(request)


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


def _message_queryset(ctx: Access) -> List[Message]:
    request = ctx.request
    statement = select(Message).where(Message.is_delete.is_(False))
    search = _query_param(request, 'search')
    if search is not None:
        statement = statement.where(Message.subject.ilike('%{}%'.format(search)))
    if _query_param(request, 'inbox') is not None:
        statement = statement.where(Message.user_id == ctx.user.id)
    if _query_param(request, 'outbox') is not None:
        statement = statement.where(Message.sender_id == ctx.user.id)
    statement = statement.where(
        or_(Message.user_id == ctx.user.id, Message.sender_id == ctx.user.id)
    )
    statement = statement.order_by(Message.id.desc()).distinct()
    return list(ctx.session.scalars(statement).unique())


@messages_router.get('/', status_code=200)
async def message_list(
    request: Request,
    ctx: Access = Depends(access(is_authenticated, allow=LIST_ALLOW)),
) -> JSONResponse:
    rows = [schemas.serialize_message(item) for item in _message_queryset(ctx)]
    return json_response(request, listing(request, rows), status_code=200)


@messages_router.post('/', status_code=201)
async def message_create(
    request: Request, ctx: Access = Depends(access(is_authenticated, allow=LIST_ALLOW))
) -> JSONResponse:
    data = await parsing.parse_body(request)
    payload = parsing.validate(schemas.MessageInput, data, schemas.MESSAGE_INPUT_ORDER)
    fields = payload.model_dump(exclude_none=True)
    # The baseline creates through BaseViewSet.perform_create(), which calls
    # serializer.save(user=self.request.user).  The posted "user" is therefore
    # discarded and the recipient is always the caller, while "sender" stays an
    # ordinary writable serializer field: a posted value is honoured and the
    # column is left null when the payload omits it.
    sender = fields.pop('sender', None)
    fields.pop('user', None)
    row = Message(**fields)
    row.user_id = ctx.user.id
    if sender is not None:
        row.sender_id = sender
    ctx.session.add(row)
    ctx.session.flush()
    ctx.session.commit()
    return json_response(request, schemas.serialize_message(row), status_code=201)


@messages_router.api_route('/', methods=list(_LIST_REST), status_code=405)
async def message_list_other(
    request: Request, ctx: Access = Depends(access(is_authenticated, allow=LIST_ALLOW))
) -> JSONResponse:
    _method_not_allowed(request)


@messages_router.get('/{pk:nodot}/', status_code=200)
async def message_detail(
    request: Request, pk: int, ctx: Access = Depends(access(is_authenticated, allow=DETAIL_ALLOW))
) -> JSONResponse:
    row = ctx.session.get(Message, pk)
    if row is None:
        raise NotFound()
    check_object_permission(ctx, row)
    return json_response(request, schemas.serialize_message(row), status_code=200)


@messages_router.api_route('/{pk:nodot}/', methods=list(_DETAIL_REST + ('PUT', 'PATCH')), status_code=405)
async def message_detail_other(
    request: Request, pk: int, ctx: Access = Depends(access(is_authenticated, allow=DETAIL_ALLOW))
) -> JSONResponse:
    _method_not_allowed(request)


router.include_router(categories_router)
router.include_router(articles_router)
router.include_router(sliders_router)
router.include_router(comments_router)
router.include_router(messages_router)


def add_head_to_get_routes(target: APIRouter) -> None:
    """Let every readable route answer ``HEAD`` with its ``GET`` handler.

    The baseline maps ``HEAD`` onto the ``get`` action, so ``HEAD`` on a public
    list endpoint answers 200 rather than 405.  Starlette does this for plain
    routes but ``APIRoute`` does not, so the twin is registered here.  The
    server suppresses the body for ``HEAD`` while keeping ``Content-Length``.
    """
    for route in target.routes:
        methods = getattr(route, 'methods', None)
        if methods and 'GET' in methods and 'HEAD' not in methods:
            route.methods = set(methods) | {'HEAD'}


add_head_to_get_routes(router)
