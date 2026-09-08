"""Block until the configured database answers.

Run before the application starts so a container that comes up ahead of
PostgreSQL waits instead of crash-looping.  The probe goes through
``app.db.connections``, the same alias registry the rest of the project
uses, which is also what the suite patches in order to count attempts.

The ``'test' not in sys.argv`` guard is kept verbatim: under a test run the
alias is resolved but never opened, so the command exercises its retry loop
without needing a server.
"""

from __future__ import annotations

import sys
import time
from typing import Any, Optional

from psycopg2 import OperationalError as Psycopg2Error
from sqlalchemy.exc import OperationalError

from app.db import connections


class OutputWrapper:
    """Line-oriented sink for a command's progress messages."""

    def __init__(self, stream: Optional[Any] = None) -> None:
        self._stream = stream

    def write(self, message: str) -> None:
        stream = self._stream if self._stream is not None else sys.stdout
        stream.write('{}\n'.format(message))


class Style:
    """Styling hooks.

    The project never turned colour on, so each style is the identity: the
    call sites keep reading as intent, and the output stays plain.
    """

    @staticmethod
    def SUCCESS(message: str) -> str:
        return message

    @staticmethod
    def ERROR(message: str) -> str:
        return message


class BaseCommand:
    """The surface a management command may rely on."""

    help = ''

    def __init__(self, stdout: Optional[Any] = None,
                 stderr: Optional[Any] = None) -> None:
        self.stdout = OutputWrapper(stdout)
        self.stderr = OutputWrapper(stderr)
        self.style = Style()


class Command(BaseCommand):

    def handle(self, *args, **options):
        self.stdout.write('Waiting for database...')
        connected = False
        while not connected:
            try:
                db_conn = connections["default"]
                if 'test' not in sys.argv:
                    db_conn.ensure_connection()
                self.stdout.write('Database is ready!...')
                connected = True
            except (OperationalError, Psycopg2Error):
                self.stdout.write('Database unavailable, waiting 1 second...')
                time.sleep(1)

        self.stdout.write(self.style.SUCCESS('Database available!'))
