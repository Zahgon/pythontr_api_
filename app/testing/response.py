"""The response object the assertions read."""

from __future__ import annotations

import json
from typing import Any

import httpx


class Response:
    """A response, plus the decoded body the assertions read."""

    def __init__(self, raw: httpx.Response) -> None:
        self._raw = raw
        self.status_code = raw.status_code
        self.data = self._decode(raw)

    @staticmethod
    def _decode(raw: httpx.Response) -> Any:
        if not raw.content:
            return None
        try:
            return json.loads(raw.content.decode('utf-8'))
        except (UnicodeDecodeError, ValueError):
            return None

    @property
    def content(self) -> bytes:
        return self._raw.content

    @property
    def text(self) -> str:
        return self._raw.text

    @property
    def headers(self) -> httpx.Headers:
        return self._raw.headers

    @property
    def cookies(self) -> httpx.Cookies:
        return self._raw.cookies

    def json(self) -> Any:
        return self._raw.json()

    def __getitem__(self, header: str) -> str:
        return self._raw.headers[header]

    def __repr__(self) -> str:
        return '<Response {} {}>'.format(
            self.status_code, self._raw.request.url.path)
