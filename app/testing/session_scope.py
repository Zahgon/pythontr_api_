"""One session for the whole test process.

``app.db.SessionLocal`` is thread scoped, which is right for a server:
concurrent requests must not share an identity map.  Under test it is
wrong, and not by a little.  A request never runs entirely on the thread
that issued it -- the transport drives the application from a worker
thread, and the session dependency is a synchronous generator, which the
framework runs in a thread pool of its own.  A row a test built would
therefore belong to one session while the route body belonged to another,
and attaching it would raise.

Widening the scope to the process removes that split.  It is safe here
precisely because it would not be safe in a server: a test blocks while its
request runs, so only ever one thread touches the session at a time.
"""

from __future__ import annotations

from sqlalchemy.util import ScopedRegistry, ThreadLocalRegistry

from app import db as _db

SCOPE = 'app.testing'


def _single_scope() -> str:
    return SCOPE


def share_session_across_threads() -> None:
    """Widen the session scope from the thread to the process. Idempotent."""
    if isinstance(_db.SessionLocal.registry, ThreadLocalRegistry):
        _db.SessionLocal.registry = ScopedRegistry(
            _db.SessionLocal.session_factory, _single_scope)
