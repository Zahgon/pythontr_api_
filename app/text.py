"""Text helpers used by the models and the schema layer."""

from __future__ import annotations

import re
import unicodedata


def slugify(value, allow_unicode: bool = False) -> str:
    """Lowercase, strip accents, collapse runs to single hyphens.

    Byte-compatible with the slugs already stored in the database, so
    existing rows keep resolving through the slug lookups.
    """
    value = str(value)
    if allow_unicode:
        value = unicodedata.normalize('NFKC', value)
    else:
        value = unicodedata.normalize('NFKD', value)
        value = value.encode('ascii', 'ignore').decode('ascii')
    value = re.sub(r'[^\w\s-]', '', value.lower())
    return re.sub(r'[-\s]+', '-', value).strip('-_')


def capfirst(value):
    if not value:
        return value
    return str(value)[0].upper() + str(value)[1:]


def get_text_list(items, last_word: str = 'or') -> str:
    items = [str(i) for i in items]
    if not items:
        return ''
    if len(items) == 1:
        return items[0]
    return '%s %s %s' % (', '.join(items[:-1]), last_word, items[-1])
