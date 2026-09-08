"""Email backend that writes messages to a stream instead of sending them."""

from __future__ import annotations

import sys
import threading
from typing import List

from app.mail.backends.base import BaseEmailBackend


class EmailBackend(BaseEmailBackend):
    """Write each message to ``stream`` (stdout by default)."""

    def __init__(self, *args, **kwargs):
        self.stream = kwargs.pop('stream', sys.stdout)
        self._lock = threading.RLock()
        super().__init__(*args, **kwargs)

    def write_message(self, message) -> None:
        self.stream.write('Subject: %s\n' % message.subject)
        self.stream.write('From: %s\n' % message.from_email)
        self.stream.write('To: %s\n' % ', '.join(message.recipients()))
        self.stream.write('\n')
        self.stream.write('%s\n' % message.body)
        self.stream.write('-' * 79)
        self.stream.write('\n')

    def send_messages(self, email_messages: List) -> int:
        if not email_messages:
            return 0
        sent = 0
        with self._lock:
            try:
                for message in email_messages:
                    self.write_message(message)
                    self.stream.flush()
                    sent += 1
            except Exception:
                if not self.fail_silently:
                    raise
        return sent
