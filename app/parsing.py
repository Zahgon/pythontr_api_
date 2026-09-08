"""Request body parsing and validation error shaping.

FastAPI's own request-body validation answers with a 422 and its own
envelope.  The baseline answers with a 400 and a field-keyed body whose
messages are Turkish, so the mutating routes read the raw body through
:func:`parse_body` and validate it through :func:`validate` instead of
declaring a Pydantic parameter.

The two functions together reproduce four observed behaviours:

* an unsupported ``Content-Type`` is a 415 with the Turkish media-type
  message,
* a malformed JSON document is a 400 whose ``detail`` embeds the standard
  library's decoder message,
* a well-formed document that fails validation is a 400 keyed by field
  name in declaration order,
* a form payload coerces list values and empty strings the way an HTML
  form does, which is what makes a missing boolean read as ``False``,
* an explicit JSON ``null`` on a field the baseline declares without
  ``allow_null`` is a 400 carrying the null message, not a type error and
  not a database failure.
"""

from __future__ import annotations

import json
from typing import (
    Any, Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple, Type,
)

from pydantic import BaseModel, ValidationError

from app.i18n import gettext as _
from app.wire import UnsupportedMediaType, ValidationFailed

JSON_MEDIA_TYPES = ('application/json',)
FORM_MEDIA_TYPES = (
    'application/x-www-form-urlencoded',
    'multipart/form-data',
)

#: Pydantic error types mapped onto the message the baseline emits.
_ERROR_MESSAGES = {
    'missing': 'This field is required.',
    'string_type': 'Not a valid string.',
    'string_too_short': 'This field may not be blank.',
    'int_parsing': 'A valid integer is required.',
    'int_type': 'A valid integer is required.',
    'bool_parsing': 'Must be a valid boolean.',
    'bool_type': 'Must be a valid boolean.',
    'list_type': 'Expected a list of items but got type "str".',
    'too_short': 'This list may not be empty.',
    'email_format': 'Enter a valid email address.',
    'value_error': 'Enter a valid value.',
}

#: The message a field emits for an explicit ``null`` it does not accept.
NULL_MESSAGE = 'This field may not be null.'


def media_type_of(request) -> str:
    """Return the request's media type without parameters."""
    header = request.headers.get('content-type', '')
    return header.split(';')[0].strip().lower()


def _decode_form_value(values: List[Any]) -> Any:
    """Collapse a repeated form field the way the baseline's parser does."""
    if len(values) == 1:
        return values[0]
    return values


async def parse_body(request, allow_form: bool = True) -> Dict[str, Any]:
    """Read and decode the request body.

    ``allow_form`` is ``False`` for the routes whose parser list holds only
    the JSON parser.  An empty body decodes to an empty mapping so that the
    validation layer reports every required field as missing, which is what
    the baseline does for ``PUT`` with no payload.
    """
    raw = await request.body()
    if 'chunked' in request.headers.get('transfer-encoding', '').lower() \
            and 'content-length' not in request.headers:
        # PEP 3333 gives the baseline no way to read a chunked payload, so it
        # sees an empty body and reports every field as missing.
        raw = b''
    media_type = media_type_of(request)

    if raw and 'content-type' not in request.headers:
        # An absent header is not an empty one: the baseline's HTTP container
        # substitutes text/plain, for which no parser is configured.  A body it
        # never reads is never negotiated, so an empty payload still decodes to
        # an empty mapping instead of being refused.
        raise UnsupportedMediaType('text/plain')

    if not media_type:
        # No declared type.  The baseline's form parser is the default, so an
        # empty declaration is treated as a form payload.
        media_type = FORM_MEDIA_TYPES[0] if allow_form else JSON_MEDIA_TYPES[0]

    if media_type in JSON_MEDIA_TYPES:
        if not raw:
            return {}
        try:
            decoded = json.loads(raw.decode('utf-8'))
        except ValueError as exc:
            raise ValidationFailed(
                {'detail': 'JSON parse error - {}'.format(exc)}
            )
        if not isinstance(decoded, dict):
            return {'non_field_errors': decoded}
        return decoded

    if allow_form and media_type in FORM_MEDIA_TYPES:
        form = await request.form()
        collected: Dict[str, List[Any]] = {}
        for key in form.keys():
            collected[key] = list(form.getlist(key))
        return {
            key: _decode_form_value(values)
            for key, values in collected.items()
        }

    raise UnsupportedMediaType(media_type)


def is_form_request(request) -> bool:
    """Report whether the payload arrived as an HTML form."""
    media_type = media_type_of(request)
    return not media_type or media_type in FORM_MEDIA_TYPES


def _location(error: Mapping[str, Any]) -> str:
    location = error.get('loc') or ()
    for part in location:
        if isinstance(part, str):
            return part
    return 'non_field_errors'


def _message(error: Mapping[str, Any]) -> str:
    error_type = str(error.get('type', ''))
    context = error.get('ctx') or {}

    if error_type in ('string_too_short', 'too_short'):
        minimum = context.get('min_length', context.get('min_length', 0))
        if error_type == 'string_too_short' and minimum and minimum > 1:
            return _('Ensure this field has at least {min_length} '
                     'characters.').format(min_length=minimum)
        if error_type == 'too_short':
            return _('This list may not be empty.')
        return _('This field may not be blank.')

    if error_type == 'value_error':
        raw = context.get('error')
        if raw is not None:
            return _(str(raw))
        return _(str(error.get('msg', 'Enter a valid value.')))

    template = _ERROR_MESSAGES.get(error_type)
    if template is None:
        return _(str(error.get('msg', 'Enter a valid value.')))
    return _(template)


def to_field_errors(exc: ValidationError,
                    order: Optional[Sequence[str]] = None
                    ) -> Dict[str, List[str]]:
    """Convert a Pydantic failure into the baseline's field-keyed body.

    Keys follow ``order`` when given so that the JSON document lists fields
    in the order the schema declares them, which is the order the baseline's
    serializers emit.
    """
    grouped: Dict[str, List[str]] = {}
    for error in exc.errors():
        field = _location(error)
        grouped.setdefault(field, []).append(_message(error))

    if order is None:
        return grouped

    ordered: Dict[str, List[str]] = {}
    for field in order:
        if field in grouped:
            ordered[field] = grouped.pop(field)
    ordered.update(grouped)
    return ordered


def nullable_fields(schema: Type[BaseModel]) -> FrozenSet[str]:
    """Return the schema fields that accept an explicit ``null``.

    The baseline's default is ``allow_null=False``, so a schema that says
    nothing rejects every null.
    """
    return frozenset(getattr(schema, 'nullable_fields', ()))


def null_errors(schema: Type[BaseModel],
                data: Mapping[str, Any]) -> Dict[str, List[str]]:
    """Report every explicit ``null`` the schema does not accept.

    The baseline checks this per field before any type or format check and
    collects the whole set, so a payload with several nulls answers with one
    entry per field rather than stopping at the first.
    """
    allowed = nullable_fields(schema)
    return {
        field: [_(NULL_MESSAGE)]
        for field in schema.model_fields
        if field not in allowed
        and field in data
        and data[field] is None
    }


def validate(schema: Type[BaseModel],
             data: Mapping[str, Any],
             order: Optional[Sequence[str]] = None) -> BaseModel:
    """Validate ``data`` or raise the baseline's 400."""
    nulls = null_errors(schema, data)
    try:
        model = schema(**dict(data))
    except ValidationError as exc:
        grouped = to_field_errors(exc)
    else:
        if not nulls:
            return model
        grouped = {}
    # A rejected null also trips the field's type check, and the baseline
    # reports only the null, so the null message replaces that entry.
    grouped.update(nulls)
    raise ValidationFailed(ordered_errors(grouped, order or ()))


def ordered_errors(errors: Dict[str, Any],
                   order: Sequence[str]) -> Dict[str, Any]:
    """Sort an error body into the serializer's declared field order.

    The baseline builds its error dict by walking ``Meta.fields``, and the
    captcha fork appends ``captcha`` to the end of that list, so a missing
    captcha is reported after the other field errors rather than before them.
    """
    ordered = {field: errors[field] for field in order if field in errors}
    for field, value in errors.items():
        if field not in ordered:
            ordered[field] = value
    return ordered


def field_order(schema: Type[BaseModel]) -> Tuple[str, ...]:
    """Return a schema's declared field names in order."""
    return tuple(schema.model_fields.keys())


def unique_error(field: str, model_name: str) -> Dict[str, List[str]]:
    """Build the body a unique-constraint violation produces."""
    message = _('Bu {field_labels} alanına sahip {model_name} zaten mevcut.')
    return {field: [message.format(field_labels=field,
                                   model_name=model_name)]}
