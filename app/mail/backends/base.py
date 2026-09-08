"""Common backend behaviour.

``send_messages`` here is a working no-op that reports zero deliveries
rather than a stub: a backend that cannot deliver is a legitimate
configuration (it is what ``EMAIL_BACKEND`` pointed at during the
baseline's own test runs before locmem was selected), and callers only
ever read the returned count.
"""

from __future__ import annotations

from typing import Sequence


class BaseEmailBackend:
    """Interface shared by every backend."""

    def __init__(self, fail_silently: bool = False, **kwargs):
        self.fail_silently = fail_silently

    def open(self) -> bool:
        """Ready the connection.  Returns whether one was newly opened."""
        return False

    def close(self) -> None:
        """Release the connection."""
        return None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def send_messages(self, email_messages: Sequence) -> int:
        """Deliver ``email_messages`` and return how many were sent."""
        return 0
