"""Request-body encoders.

Writes default to ``multipart/form-data``, which is what the suite was
written against.  A sequence value contributes one part per element under
the same field name, so ``{'categories': [5]}`` arrives as a single
``categories`` part carrying ``5`` -- which is what makes a one-element
list read back as a one-element list rather than as the string ``'[5]'``.
An empty sequence and a ``None`` contribute nothing.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterator, List, Optional

#: Fixed so that a recorded request body is byte-for-byte reproducible.
BOUNDARY = 'BoUnDaRyStRiNgOfThEpYtHoNtRtEsTsUiTe'

MULTIPART_CONTENT = 'multipart/form-data; boundary={}'.format(BOUNDARY)
JSON_CONTENT = 'application/json'


def _iter_values(value: Any) -> Iterator[Any]:
    """Yield the scalar parts a single field contributes to the body."""
    if value is None:
        return
    if isinstance(value, (str, bytes)):
        yield value
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            for scalar in _iter_values(item):
                yield scalar
        return
    yield value


def _render(item: Any) -> str:
    if isinstance(item, bytes):
        return item.decode('utf-8')
    return str(item)


def encode_multipart(data: Optional[Dict[str, Any]],
                     boundary: str = BOUNDARY) -> bytes:
    """Encode ``data`` as a ``multipart/form-data`` body.

    A sequence value contributes one part per element under the same field
    name; an empty sequence and a ``None`` contribute nothing, which is the
    convention the source suite's payloads were written for.
    """
    lines: List[str] = []
    for key, value in (data or {}).items():
        for item in _iter_values(value):
            lines.append('--' + boundary)
            lines.append(
                'Content-Disposition: form-data; name="{}"'.format(key))
            lines.append('')
            lines.append(_render(item))
    lines.append('--' + boundary + '--')
    lines.append('')
    return '\r\n'.join(lines).encode('utf-8')


def _encode_json(data: Optional[Dict[str, Any]]) -> bytes:
    return json.dumps(
        data if data is not None else {},
        ensure_ascii=False,
        default=str,
    ).encode('utf-8')
