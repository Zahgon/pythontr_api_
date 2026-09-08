"""Translation lookup.

Two vocabularies pass through here and they behave differently, exactly
as they did on the baseline:

*   The **framework** vocabulary -- the handful of messages the request
    layer itself emits (authentication, permissions, method resolution,
    field validation).  The baseline shipped a compiled catalogue for
    these, so they render in Turkish.  They are held in ``_CATALOG``
    below, keyed by the original English message.

*   The **project** vocabulary -- ``not_found``, ``email_not_found``,
    ``invalid_link`` and friends.  The repository ships ``.po`` sources
    and no compiled catalogue, so on the baseline these render as the
    bare key.  They are absent from ``_CATALOG`` and therefore fall
    through unchanged.  That is deliberate: the wire contract contains
    the bare keys.
"""

from __future__ import annotations

from typing import Any, Dict

LANGUAGE_CODE = 'tr'

#: Framework messages that the baseline rendered from its compiled
#: Turkish catalogue.  Keys are the untranslated messages.
_CATALOG: Dict[str, str] = {
    'Authentication credentials were not provided.':
        'Giriş bilgileri verilmedi.',
    'Invalid token.':
        'Geçersiz simge.',
    'You do not have permission to perform this action.':
        'Bu işlemi yapmak için izniniz bulunmuyor.',
    'Method "{method}" not allowed.':
        '"{method}" metoduna izin verilmiyor.',
    'This field is required.':
        'Bu alan zorunlu.',
    'This field may not be blank.':
        'Bu alan boş bırakılmamalı.',
    'This field may not be null.':
        'Bu alan boş bırakılmamalı.',
    'Ensure this field has at least {min_length} characters.':
        'Bu alanın en az {min_length} karakter barındırdığından emin olun.',
    'The fields {field_labels} must make a unique set.':
        'Bu {field_labels} alanına sahip {model_name} zaten mevcut.',
    '{model_name} with this {field_labels} already exists.':
        'Bu {field_labels} alanına sahip {model_name} zaten mevcut.',
    'Could not satisfy the request Accept header.':
        'İsteğe ait Accept başlık bilgisi yanıt verilecek başlık bilgileri '
        'arasında değil.',
    'Unsupported media type "{media_type}" in request.':
        'İstekte desteklenmeyen medya tipi: "{media_type}".',
    'Invalid pk "{pk_value}" - object does not exist.':
        'Geçersiz pk "{pk_value}" - obje bulunamadı.',
    'Not found.':
        'Bulunamadı.',
    'Invalid page.':
        'Geçersiz sayfa.',
    'Invalid token header. No credentials provided.':
        'Geçersiz token başlığı. Kimlik bilgileri eksik.',
    'Invalid token header. Token string should not contain spaces.':
        "Geçersiz token başlığı. Token'da boşluk olmamalı.",
    'Invalid token header. Token string should not contain invalid characters.':
        'Geçersiz token başlığı. Token geçersiz karakter içermemeli.',
    'User inactive or deleted.':
        'Kullanıcı aktif değil ya da silinmiş.',
    'A valid integer is required.':
        'Geçerli bir tam sayı giriniz.',
    'Enter a valid email address.':
        'Geçerli bir e-posta adresi girin.',
    'This list may not be empty.':
        'Bu liste boş olmamalı.',
    'Not a valid string.':
        'Geçerli bir dizgi değil.',
    'Must be a valid boolean.':
        'Geçerli bir boolean değeri giriniz.',
    'Expected a list of items but got type "str".':
        'Öğelerin listesi bekleniyordu fakat "str" tipi alındı.',
    'Enter a valid value.':
        'Geçerli bir değer giriniz.',
    'Unable to log in with provided credentials.':
        'Verilen bilgiler ile giriş sağlanamadı.',
}


class LazyString(str):
    """A string that is already resolved.

    The catalogue is static, so there is nothing to defer; the type is
    kept because ``settings`` and the schemas annotate with it and the
    baseline's call sites pass these values straight into ``str``
    formatting.
    """

    __slots__ = ()


def gettext(message: Any) -> str:
    """Translate ``message``, or return it unchanged."""
    text = str(message)
    return _CATALOG.get(text, text)


def gettext_lazy(message: Any) -> LazyString:
    return LazyString(gettext(message))


def ngettext(singular: Any, plural: Any, number: int) -> str:
    return gettext(singular if number == 1 else plural)


#: Short alias matching the baseline's import style.
_ = gettext
