"""Public user endpoints.

Mounted by :mod:`app.main` under the ``/api/user`` prefix. Each path registers
real method decorators for the actions the baseline maps plus one
complement-methods handler that authenticates and evaluates permissions before
raising 405, which is why an anonymous ``POST /api/user/me/`` answers 401 while
``GET /api/user/token/`` answers 405.
"""

from __future__ import annotations

import smtplib
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Request
from starlette.responses import Response
from sqlalchemy import select

from app import settings
from app.deps import Access, access, allow_any, is_authenticated
from app.i18n import gettext as _
from app.mail import send_mail
from app.parsing import ordered_errors, parse_body, unique_error, validate
from app.security import (
    default_token_generator,
    urlsafe_base64_decode,
    urlsafe_base64_encode,
)
from app.wire import MethodNotAllowed, ValidationFailed, json_response
from core.models import ActivationCode, Token, User
from user.schemas import (
    AUTH_TOKEN_INPUT_ORDER,
    PASSWORD_RESET_CONFIRM_INPUT_ORDER,
    PASSWORD_RESET_INPUT_ORDER,
    RESEND_ACTIVATION_INPUT_ORDER,
    USER_INPUT_ORDER,
    USER_UPDATE_INPUT_ORDER,
    WRITABLE_FIELDS,
    AuthTokenInput,
    PasswordResetConfirmInput,
    PasswordResetInput,
    ResendActivationInput,
    UserInput,
    UserUpdateInput,
    captcha_errors,
    serialize_user,
)

router = APIRouter()

POST_ALLOW = ('POST', 'OPTIONS')
POST_REST = ('GET', 'PUT', 'PATCH', 'DELETE')
ME_ALLOW = ('GET', 'PUT', 'PATCH', 'HEAD', 'OPTIONS')
ME_REST = ('POST', 'DELETE', 'OPTIONS')
GET_ALLOW = ('GET', 'HEAD', 'OPTIONS')
GET_REST = ('POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS')
CONFIRM_ALLOW = ('GET', 'POST', 'HEAD', 'OPTIONS')
CONFIRM_POST_REST = ('PUT', 'PATCH', 'DELETE', 'OPTIONS')
CONFIRM_GET_REST = ('PUT', 'PATCH', 'DELETE', 'OPTIONS')


REPLACE_REQUIRED_FIELDS = ('email', 'password', 'username')


def _missing_required(data: Dict[str, Any],
                      extra: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Field-level required errors for a non-partial update.

    ``UserSerializer`` is a ModelSerializer, so a ``PUT`` runs with
    ``partial=False`` and every model field that is neither blank nor
    defaulted is required.  Those errors are raised at field level, before
    ``validate()`` sees the payload, and they come out in the serializer's
    declared field order.
    """
    errors = dict(extra or {})
    for field in REPLACE_REQUIRED_FIELDS:
        if field not in data:
            errors[field] = [_('This field is required.')]
    if not errors:
        return {}
    return {
        field: errors[field]
        for field in USER_UPDATE_INPUT_ORDER
        if field in errors
    }


def _validate_with_captcha(schema: Any, data: Dict[str, Any], order: Any) -> Any:
    """Validate a payload the way the baseline's serializers do.

    The baseline declares the captcha field on the serializer itself, so DRF
    collects a missing captcha in the same pass as the other field errors and
    reports them together rather than rejecting on the captcha first.
    """
    captcha: Dict[str, Any] = dict(captcha_errors(data) or {})
    try:
        payload = validate(schema, data, order=order)
    except ValidationFailed as exc:
        errors = dict(exc.detail)
        errors.update(captcha)
        raise ValidationFailed(ordered_errors(errors, order)) from None
    if captcha:
        raise ValidationFailed(captcha)
    return payload


def _check_passwords(data: Dict[str, Any]) -> None:
    """Reproduce ``UserSerializer.validate``'s password trio checks."""
    password = data.get('password')
    if not password:
        return
    if not data.get('confirm_password'):
        raise ValidationFailed({'confirm_password': [_('please_confirm_your_password')]})
    if password != data['confirm_password']:
        raise ValidationFailed({'non_field_errors': [_('passwords_do_not_match')]})


@router.post('/create/', status_code=201)
async def create_user(
    request: Request,
    ctx: Access = Depends(access(allow_any, allow=POST_ALLOW)),
) -> Any:
    data = await parse_body(request)
    payload = _validate_with_captcha(UserInput, data, USER_INPUT_ORDER)

    existing = ctx.session.scalars(
        select(User).where(User.email == payload.email)
    ).first()
    if existing is not None:
        raise ValidationFailed(unique_error('email', 'user'))

    _check_passwords(data)

    extra = {
        field: getattr(payload, field)
        for field in WRITABLE_FIELDS
        if field != 'email' and getattr(payload, field) is not None
    }
    # ``create()`` forces is_staff False regardless of what the payload asked for.
    extra['is_staff'] = False
    user = User.objects.create_user(
        email=payload.email,
        password=payload.password,
        session=ctx.session,
        **extra
    )

    activation = ActivationCode.create_activation_code(user, session=ctx.session)
    try:
        send_mail(
            _('welcome_to_www'),
            _('welcome_to_www_message').format(
                link='{}/register/activate/{}'.format(settings.SITE_URL, activation.code),
                expires_at=activation.expires_at.strftime('%d/%m/%Y %H:%M'),
            ),
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=False,
        )
    except smtplib.SMTPException:
        # The baseline builds a 500 response here but the framework discards the
        # return value of perform_create, so the client still receives 201.
        pass
    ctx.session.commit()
    return json_response(request, serialize_user(user), status_code=201)


@router.api_route('/create/', methods=list(POST_REST))
async def create_user_rest(
    request: Request,
    ctx: Access = Depends(access(allow_any, allow=POST_ALLOW)),
) -> Any:
    raise MethodNotAllowed(request.method)


@router.post('/token/')
async def create_token(
    request: Request,
    ctx: Access = Depends(access(allow_any, allow=POST_ALLOW)),
) -> Any:
    data = await parse_body(request)
    payload = _validate_with_captcha(AuthTokenInput, data, AUTH_TOKEN_INPUT_ORDER)

    user = ctx.session.scalars(
        select(User).where(User.email == payload.email)
    ).first()
    if user is None or not user.check_password(payload.password) or not user.is_active:
        raise ValidationFailed(
            {'non_field_errors': [_('unable_to_authenticate_with_provided_credentials')]}
        )

    token = ctx.session.scalars(
        select(Token).where(Token.user_id == user.id)
    ).first()
    if token is None:
        token = Token(user_id=user.id)
        token.save(session=ctx.session)
    ctx.session.commit()
    return json_response(request, {'token': token.key})


@router.api_route('/token/', methods=list(POST_REST))
async def create_token_rest(
    request: Request,
    ctx: Access = Depends(access(allow_any, allow=POST_ALLOW)),
) -> Any:
    raise MethodNotAllowed(request.method)


@router.get('/me/')
async def retrieve_me(
    request: Request,
    ctx: Access = Depends(access(is_authenticated, allow=ME_ALLOW)),
) -> Any:
    return json_response(request, serialize_user(ctx.user))


async def _update_me(request: Request, ctx: Access, partial: bool) -> Any:
    data = await parse_body(request)
    # A ``PATCH`` reaches the baseline's serializer with ``partial=True``, which
    # suspends every ``required`` flag -- including the captcha field's -- so a
    # partial profile update is accepted without a captcha.
    errors = None if partial else captcha_errors(data)
    if not partial:
        errors = _missing_required(data, errors) or errors
    if errors:
        raise ValidationFailed(errors)
    payload = validate(UserUpdateInput, data, order=USER_UPDATE_INPUT_ORDER)
    _check_passwords(data)

    if data.get('password'):
        if not data.get('current_password'):
            raise ValidationFailed(
                {'current_password': [_('please_enter_your_current_password')]}
            )
        if not ctx.user.check_password(data['current_password']):
            raise ValidationFailed(
                {'current_password': [_('current_password_is_incorrect')]}
            )
    if payload.is_staff is not None and payload.is_staff != ctx.user.is_staff:
        if not ctx.user.is_staff:
            raise ValidationFailed(
                {'is_staff': [_('only_staff_can_modify_staff_status')]}
            )

    if not partial:
        # ``UserSerializer.update`` pops both confirmation fields without a
        # default on a non-partial update.  Neither pop can raise: reaching
        # here means ``password`` was supplied (it is required above), and
        # ``_check_passwords`` plus the current-password check have already
        # rejected a payload that omits either confirmation field.  The two
        # lookups are kept because the baseline keeps the same two pops.
        data['confirm_password']
        data['current_password']

    for field in WRITABLE_FIELDS:
        value = getattr(payload, field)
        if value is not None:
            setattr(ctx.user, field, value)
    if payload.password:
        ctx.user.set_password(payload.password)
    ctx.user.save(session=ctx.session)
    ctx.session.commit()
    return json_response(request, serialize_user(ctx.user))


@router.put('/me/')
async def replace_me(
    request: Request,
    ctx: Access = Depends(access(is_authenticated, allow=ME_ALLOW)),
) -> Any:
    return await _update_me(request, ctx, partial=False)


@router.patch('/me/')
async def patch_me(
    request: Request,
    ctx: Access = Depends(access(is_authenticated, allow=ME_ALLOW)),
) -> Any:
    return await _update_me(request, ctx, partial=True)


@router.api_route('/me/', methods=list(ME_REST))
async def me_rest(
    request: Request,
    ctx: Access = Depends(access(is_authenticated, allow=ME_ALLOW)),
) -> Any:
    raise MethodNotAllowed(request.method)


def _route_miss(request: Request) -> Response:
    # The baseline declares this segment with a uuid path converter, so a
    # malformed value never resolves to a view: it falls through to the
    # framework 404 page with no Allow header. Dropping the Allow tuple is
    # what lets NotFoundMiddleware recognise it as a routing miss.
    request.scope.pop('allow_methods', None)
    return Response(status_code=404)


@router.get('/activate/{code}/')
async def activate_user(
    request: Request,
    code: str,
    ctx: Access = Depends(access(allow_any, allow=GET_ALLOW)),
) -> Any:
    try:
        parsed = uuid.UUID(code)
    except ValueError:
        return _route_miss(request)
    activation = ctx.session.scalars(
        select(ActivationCode).where(
            ActivationCode.code == parsed,
            ActivationCode.is_used.is_(False),
        )
    ).first()
    if activation is None:
        return json_response(
            request, {'error': _('activation_code_is_invalid')}, status_code=400
        )
    if activation.is_expired:
        return json_response(
            request, {'error': _('activation_code_is_expired')}, status_code=400
        )
    activation.user.is_active = True
    activation.is_used = True
    ctx.session.commit()
    return json_response(request, {'message': _('account_activated_successfully')})


@router.api_route('/activate/{code}/', methods=list(GET_REST))
async def activate_user_rest(
    request: Request,
    code: str,
    ctx: Access = Depends(access(allow_any, allow=GET_ALLOW)),
) -> Any:
    raise MethodNotAllowed(request.method)


@router.post('/resend-activation/')
async def resend_activation(
    request: Request,
    ctx: Access = Depends(access(allow_any, allow=POST_ALLOW)),
) -> Any:
    data = await parse_body(request)
    payload = _validate_with_captcha(ResendActivationInput, data, RESEND_ACTIVATION_INPUT_ORDER)

    user = ctx.session.scalars(
        select(User).where(User.email == payload.email, User.is_active.is_(False))
    ).first()
    if user is None:
        return json_response(
            request, {'error': _('user_not_found_with_active_code')}, status_code=400
        )

    activation = ActivationCode.create_activation_code(user, session=ctx.session)
    try:
        send_mail(
            _('new_activation_code_title'),
            _('new_activation_code_message').format(
                link='{}/register/activate/{}'.format(settings.SITE_URL, activation.code),
                expires_at=activation.expires_at.strftime('%d/%m/%Y %H:%M'),
            ),
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=False,
        )
    except smtplib.SMTPException as exc:
        return json_response(
            request,
            {'error': _('error_sending_email'), 'detail': str(exc)},
            status_code=500,
        )
    ctx.session.commit()
    return json_response(request, {'message': _('new_activation_code_sent')})


@router.api_route('/resend-activation/', methods=list(POST_REST))
async def resend_activation_rest(
    request: Request,
    ctx: Access = Depends(access(allow_any, allow=POST_ALLOW)),
) -> Any:
    raise MethodNotAllowed(request.method)


@router.post('/reset-password/')
async def reset_password(
    request: Request,
    ctx: Access = Depends(access(allow_any, allow=POST_ALLOW)),
) -> Any:
    data = await parse_body(request)
    captcha: Dict[str, Any] = dict(captcha_errors(data) or {})
    try:
        payload = validate(PasswordResetInput, data, order=PASSWORD_RESET_INPUT_ORDER)
    except ValidationFailed as exc:
        errors = dict(exc.detail)
        errors.update(captcha)
        raise ValidationFailed(ordered_errors(errors, PASSWORD_RESET_INPUT_ORDER)) from None

    user = ctx.session.scalars(
        select(User).where(User.email == payload.email)
    ).first()
    if user is None:
        # The baseline raises a dict inside a field validator, so the error
        # nests one level deeper than a normal field error.  Being a field
        # validator, it also runs in the same pass as the captcha check, so
        # both errors are reported together.
        errors = {'email': {'error': _('email_not_found')}}
        errors.update(captcha)
        raise ValidationFailed(ordered_errors(errors, PASSWORD_RESET_INPUT_ORDER))
    if captcha:
        raise ValidationFailed(captcha)

    token = default_token_generator.make_token(user)
    uidb64 = urlsafe_base64_encode(str(user.pk).encode('utf-8'))
    reset_url = '{}/forgot-password/{}/{}'.format(settings.SITE_URL, uidb64, token)
    try:
        send_mail(
            _('password_reset_title'),
            _('password_reset_message').format(link=reset_url),
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=False,
        )
    except smtplib.SMTPException as exc:
        return json_response(
            request,
            {'error': _('error_sending_email'), 'detail': str(exc)},
            status_code=500,
        )
    return json_response(
        request, {'message': _('password_reset_success_message_link_sent')}
    )


@router.api_route('/reset-password/', methods=list(POST_REST))
async def reset_password_rest(
    request: Request,
    ctx: Access = Depends(access(allow_any, allow=POST_ALLOW)),
) -> Any:
    raise MethodNotAllowed(request.method)


def _user_from_uidb64(session: Any, uidb64: str) -> Optional[User]:
    uid = urlsafe_base64_decode(uidb64).decode('utf-8')
    return session.get(User, int(uid))


@router.post('/reset-password/confirm/')
async def reset_password_confirm(
    request: Request,
    ctx: Access = Depends(access(allow_any, allow=CONFIRM_ALLOW)),
) -> Any:
    data = await parse_body(request)
    payload = _validate_with_captcha(PasswordResetConfirmInput, data, PASSWORD_RESET_CONFIRM_INPUT_ORDER)

    if payload.password != payload.confirm_password:
        raise ValidationFailed({'confirm_password': [_('passwords_do_not_match')]})

    try:
        user = _user_from_uidb64(ctx.session, payload.uidb64)
    except (TypeError, ValueError, UnicodeDecodeError):
        user = None
    if user is None:
        raise ValidationFailed({'error': [_('invalid_link')]})
    if not default_token_generator.check_token(user, payload.token):
        raise ValidationFailed({'error': [_('invalid_link_or_expired')]})

    user.set_password(payload.password)
    user.save(session=ctx.session)
    ctx.session.commit()
    return json_response(request, {'message': _('password_reset_success_message')})


@router.api_route('/reset-password/confirm/', methods=list(CONFIRM_POST_REST))
async def reset_password_confirm_rest(
    request: Request,
    ctx: Access = Depends(access(allow_any, allow=CONFIRM_ALLOW)),
) -> Any:
    raise MethodNotAllowed(request.method)


@router.get('/reset-password/confirm/{uidb64}/{token}/')
async def reset_password_confirm_check(
    request: Request,
    uidb64: str,
    token: str,
    ctx: Access = Depends(access(allow_any, allow=CONFIRM_ALLOW)),
) -> Any:
    try:
        user = _user_from_uidb64(ctx.session, uidb64)
        if user is None:
            raise ValueError('unknown user')
    except (TypeError, ValueError, UnicodeDecodeError):
        return json_response(request, {'error': _('invalid_link')}, status_code=400)
    if not default_token_generator.check_token(user, token):
        return json_response(
            request, {'error': _('invalid_token_or_expired')}, status_code=400
        )
    return json_response(request, {'valid': True})


@router.api_route(
    '/reset-password/confirm/{uidb64}/{token}/', methods=list(CONFIRM_GET_REST)
)
async def reset_password_confirm_check_rest(
    request: Request,
    uidb64: str,
    token: str,
    ctx: Access = Depends(access(allow_any, allow=CONFIRM_ALLOW)),
) -> Any:
    raise MethodNotAllowed(request.method)


def add_head_to_get_routes(target: APIRouter) -> None:
    """Map HEAD onto every GET route, as the baseline's dispatcher does."""
    for route in target.routes:
        methods = getattr(route, 'methods', None)
        if methods and 'GET' in methods and 'HEAD' not in methods:
            route.methods = set(methods) | {'HEAD'}


add_head_to_get_routes(router)
