"""In-memory backend.

Appends to :data:`app.mail.outbox` instead of delivering.  The test suite
and the probe environment both select this backend, and the tests read
the outbox to assert that activation and reset mails were queued.
"""

from __future__ import annotations

from typing import Sequence

from app import mail
from app.mail.backends.base import BaseEmailBackend


class EmailBackend(BaseEmailBackend):
    """Collect messages in ``app.mail.outbox``."""

    def send_messages(self, email_messages: Sequence) -> int:
        if not email_messages:
            return 0
        for message in email_messages:
            mail.outbox.append(message)
        return len(email_messages)
