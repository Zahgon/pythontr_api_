"""Outgoing mail.

A thin send path with pluggable backends, selected by dotted path from
``settings.EMAIL_BACKEND``.  The views call :func:`send_mail` and let
``SMTPException`` propagate, exactly as the baseline did.
"""

from __future__ import annotations

import importlib
from typing import List, Optional, Sequence

from app import settings


class EmailMessage:
    """A single outbound message."""

    def __init__(
        self,
        subject: str = '',
        body: str = '',
        from_email: Optional[str] = None,
        to: Optional[Sequence[str]] = None,
        connection=None,
    ):
        self.subject = subject
        self.body = body
        self.from_email = from_email or settings.DEFAULT_FROM_EMAIL
        self.to = list(to or [])
        self.connection = connection

    @property
    def recipients(self) -> List[str]:
        return list(self.to)

    def send(self, fail_silently: bool = False) -> int:
        connection = self.connection or get_connection(fail_silently=fail_silently)
        return connection.send_messages([self])


def get_connection(backend: Optional[str] = None, fail_silently: bool = False, **kwargs):
    """Load and instantiate the configured backend."""
    path = backend or settings.EMAIL_BACKEND
    module_path, class_name = path.rsplit('.', 1)
    module = importlib.import_module(module_path)
    klass = getattr(module, class_name)
    return klass(fail_silently=fail_silently, **kwargs)


def send_mail(
    subject: str,
    message: str,
    from_email: Optional[str],
    recipient_list: Sequence[str],
    fail_silently: bool = False,
    connection=None,
) -> int:
    """Send one message and return the number of messages delivered."""
    connection = connection or get_connection(fail_silently=fail_silently)
    mail = EmailMessage(
        subject=subject,
        body=message,
        from_email=from_email,
        to=recipient_list,
        connection=connection,
    )
    return mail.send(fail_silently=fail_silently)


#: Populated by the locmem backend; the tests read it.
outbox: List[EmailMessage] = []
