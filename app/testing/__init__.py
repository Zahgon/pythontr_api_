"""In-process HTTP client and test-case base for the project's suite.

The pieces live one responsibility per module -- :mod:`app.testing.encoding`
builds request bodies, :mod:`app.testing.response` decodes replies,
:mod:`app.testing.client` drives the ASGI application and
:mod:`app.testing.case` is what a test subclasses -- and this package is
their single import surface, so a test module keeps writing
``from app.testing import APIClient, TestCase``.

Importing this package widens the session scope from the thread to the
process, because importing it means the process is a test run.
"""

from __future__ import annotations

from app.testing.case import (
    Client,
    TestCase,
    call_command,
    get_user_model,
    is_fixture_factory,
)
from app.testing.client import APIClient
from app.testing.encoding import (
    BOUNDARY,
    JSON_CONTENT,
    MULTIPART_CONTENT,
    encode_multipart,
)
from app.testing.response import Response
from app.testing.session_scope import share_session_across_threads

share_session_across_threads()

__all__ = [
    'APIClient',
    'BOUNDARY',
    'Client',
    'JSON_CONTENT',
    'MULTIPART_CONTENT',
    'Response',
    'TestCase',
    'call_command',
    'encode_multipart',
    'get_user_model',
    'is_fixture_factory',
    'share_session_across_threads',
]
