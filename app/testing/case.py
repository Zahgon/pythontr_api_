"""The ``unittest`` base class and the command runner the suite uses."""

from __future__ import annotations

import importlib
import inspect
import unittest
from typing import Any, Optional, Sequence

from app import db as _db
from app.testing.client import APIClient
from app.testing.response import Response


def get_user_model() -> Any:
    """Return the model ``settings.AUTH_USER_MODEL`` names."""
    from core.models import User

    return User


#: The administration tests instantiate a plain browser-style client; it is
#: the same object, because the harness draws no distinction between them.
Client = APIClient


def call_command(name: str, *args: Any, **options: Any) -> Any:
    """Run ``core/management/commands/<name>.py``.

    Prefers the command's ``execute`` entry point when it defines one, so
    that any output plumbing a command sets up still runs.
    """
    module = importlib.import_module(
        'core.management.commands.{}'.format(name))
    command = module.Command()
    runner = getattr(command, 'execute', None)
    if runner is None or not callable(runner):
        runner = command.handle
    return runner(*args, **options)


class TestCase(unittest.TestCase):
    """Base class for the suite.

    ``self.client`` and ``self.session`` are built on first use rather than
    in ``setUp``, so a subclass that overrides ``setUp`` without chaining up
    still gets working attributes -- and a subclass that assigns its own
    client simply replaces the stored one.

    The surrounding transaction is opened and rolled back by the autouse
    fixture in the root ``conftest.py``; ``self.session`` is bound to that
    connection, so rows a test writes through the session and rows it
    writes through the API are the same rows, and none of them survive the
    test.
    """

    client_class = APIClient

    _client: Optional[APIClient] = None

    @property
    def client(self) -> APIClient:
        if self._client is None:
            self._client = self.client_class()
        return self._client

    @client.setter
    def client(self, value: APIClient) -> None:
        self._client = value

    @property
    def session(self) -> Any:
        return _db.get_session()

    def assertContains(self, response: Response, text: Any,
                       count: Optional[int] = None, status_code: int = 200,
                       msg_prefix: str = '') -> None:
        """Assert ``text`` appears in ``response``'s rendered body."""
        self.assertEqual(
            response.status_code, status_code,
            '{}unexpected status code'.format(_prefix(msg_prefix)))
        body = response.content.decode('utf-8', 'replace')
        found = body.count(str(text))
        if count is None:
            self.assertGreater(
                found, 0,
                '{}could not find {!r} in the response'.format(
                    _prefix(msg_prefix), text))
        else:
            self.assertEqual(
                found, count,
                '{}found {!r} {} time(s), expected {}'.format(
                    _prefix(msg_prefix), text, found, count))

    def assertNotContains(self, response: Response, text: Any,
                          status_code: int = 200,
                          msg_prefix: str = '') -> None:
        self.assertEqual(
            response.status_code, status_code,
            '{}unexpected status code'.format(_prefix(msg_prefix)))
        body = response.content.decode('utf-8', 'replace')
        self.assertNotIn(
            str(text), body,
            '{}unexpectedly found {!r} in the response'.format(
                _prefix(msg_prefix), text))


def _prefix(msg_prefix: str) -> str:
    return '{}: '.format(msg_prefix) if msg_prefix else ''


def is_fixture_factory(name: str, obj: Any,
                       known: Sequence[str] = ()) -> bool:
    """Report whether a module-level ``test_*`` name is a helper, not a test.

    The source suite carries factories called ``test_user`` /
    ``test_category`` that build rows for the classes below them.  Class
    based discovery never ran them; name based discovery would, and they
    would then write outside any test's transaction.  A factory is
    recognised by shape -- it takes parameters and every one of them has a
    default, which no real test does -- with an explicit name list as a
    backstop.
    """
    if not name.startswith('test'):
        return False
    if not inspect.isfunction(obj):
        return False
    if name in known:
        return True
    parameters = list(inspect.signature(obj).parameters.values())
    if not parameters:
        return False
    return all(
        parameter.default is not inspect.Parameter.empty
        for parameter in parameters
    )
