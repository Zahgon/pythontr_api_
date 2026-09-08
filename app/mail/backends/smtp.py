"""SMTP backend.

Opens a real connection using the ``EMAIL_*`` settings.  ``SMTPException``
is allowed to propagate unless ``fail_silently`` is set, because the user
views catch it and turn it into a 500 body of their own.
"""

from __future__ import annotations

import smtplib
from email.mime.text import MIMEText
from typing import Optional, Sequence

from app import settings
from app.mail.backends.base import BaseEmailBackend


class EmailBackend(BaseEmailBackend):
    """Deliver over SMTP."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        use_tls: Optional[bool] = None,
        fail_silently: bool = False,
        **kwargs
    ):
        super().__init__(fail_silently=fail_silently, **kwargs)
        self.host = host if host is not None else settings.EMAIL_HOST
        self.port = port if port is not None else settings.EMAIL_PORT
        self.username = username if username is not None else settings.EMAIL_HOST_USER
        self.password = (
            password if password is not None else settings.EMAIL_HOST_PASSWORD
        )
        self.use_tls = use_tls if use_tls is not None else settings.EMAIL_USE_TLS
        self.connection = None

    def open(self) -> bool:
        if self.connection is not None:
            return False
        try:
            self.connection = smtplib.SMTP(self.host, self.port)
            if self.use_tls:
                self.connection.starttls()
            if self.username and self.password:
                self.connection.login(self.username, self.password)
            return True
        except (smtplib.SMTPException, OSError):
            if not self.fail_silently:
                raise
            return False

    def close(self) -> None:
        if self.connection is None:
            return
        try:
            self.connection.quit()
        except (smtplib.SMTPException, OSError):
            if not self.fail_silently:
                raise
        finally:
            self.connection = None

    def send_messages(self, email_messages: Sequence) -> int:
        if not email_messages:
            return 0
        self.open()
        if self.connection is None:
            return 0
        sent = 0
        try:
            for message in email_messages:
                if self._send(message):
                    sent += 1
        finally:
            self.close()
        return sent

    def _send(self, message) -> bool:
        if not message.recipients:
            return False
        mime = MIMEText(message.body, 'plain', 'utf-8')
        mime['Subject'] = message.subject
        mime['From'] = message.from_email
        mime['To'] = ', '.join(message.recipients)
        try:
            self.connection.sendmail(
                message.from_email, message.recipients, mime.as_string(),
            )
        except smtplib.SMTPException:
            if not self.fail_silently:
                raise
            return False
        return True
