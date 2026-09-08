"""SQLAlchemy engine, declarative base and request-scoped session handling.

The project talks to the same PostgreSQL schema the baseline used, so the
table names declared by the models in :mod:`core.models` are authoritative
and must not drift.  ``get_session`` is what the FastAPI dependency in
:mod:`app.deps` yields; tests swap in a shared connection so that every test
runs inside a transaction that is rolled back afterwards.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy import BigInteger, Integer, create_engine
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import DeclarativeBase, Session, scoped_session, sessionmaker

from app import settings


BIG_PK = BigInteger().with_variant(Integer, 'sqlite')
"""Identifier type for every table.

SQLite only auto-assigns a rowid to a column declared exactly
``INTEGER PRIMARY KEY``; a ``BIGINT`` primary key is an ordinary NOT NULL
column there, so an insert that omits the identifier fails.  The variant
keeps PostgreSQL on ``bigint`` while letting the SQLite fallback work.
"""


class Base(DeclarativeBase):
    """Declarative base shared by every model in the project."""


def build_url() -> str:
    """Return the SQLAlchemy URL described by the ``DB_*`` settings."""
    engine = (settings.DATABASES['default'].get('ENGINE') or '').lower()
    name = settings.DATABASES['default'].get('NAME') or ''
    if 'sqlite' in engine:
        return 'sqlite+pysqlite:///%s' % name
    host = settings.DATABASES['default'].get('HOST') or 'localhost'
    port = settings.DATABASES['default'].get('PORT') or 5432
    user = settings.DATABASES['default'].get('USER') or ''
    password = settings.DATABASES['default'].get('PASSWORD') or ''
    return 'postgresql+psycopg2://%s:%s@%s:%s/%s' % (
        user, password, host, port, name,
    )


_engine: Optional[Engine] = None
_shared_connection: Optional[Connection] = None


def get_engine() -> Engine:
    """Return the process-wide engine, building it on first use."""
    global _engine
    if _engine is None:
        url = build_url()
        options: Dict[str, Any] = {'future': True, 'pool_pre_ping': True}
        if url.startswith('sqlite'):
            options['connect_args'] = {'check_same_thread': False}
            options.pop('pool_pre_ping')
        _engine = create_engine(url, **options)
    return _engine


def reset_engine() -> None:
    """Dispose of the current engine so the next call rebuilds it."""
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


def set_shared_connection(connection: Optional[Connection]) -> None:
    """Bind every future session to ``connection`` (used by the test suite)."""
    global _shared_connection
    _shared_connection = connection
    SessionLocal.remove()


def get_shared_connection() -> Optional[Connection]:
    return _shared_connection


def _session_bind():
    if _shared_connection is not None:
        return _shared_connection
    return get_engine()


SessionLocal = scoped_session(
    sessionmaker(
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
        future=True,
        class_=Session,
    ),
)


def get_session() -> Session:
    """Return the session bound to the current scope, creating it if needed."""
    if not SessionLocal.registry.has():
        SessionLocal.configure(bind=_session_bind())
    session = SessionLocal()
    if session.get_bind() is not _session_bind():
        SessionLocal.remove()
        SessionLocal.configure(bind=_session_bind())
        session = SessionLocal()
    return session


def remove_session() -> None:
    """Drop the session bound to the current scope."""
    SessionLocal.remove()


def create_all() -> None:
    """Create every table declared on :class:`Base` (used by the test setup)."""
    Base.metadata.create_all(bind=_session_bind())


def drop_all() -> None:
    Base.metadata.drop_all(bind=_session_bind())


class _Connection:
    """Handle for one configured database alias.

    ``wait_for_db`` probes the database through ``ensure_connection``; that
    is the only method anything calls.
    """

    def __init__(self, alias: str) -> None:
        self.alias = alias

    def ensure_connection(self) -> None:
        """Open and immediately release a connection, or raise trying."""
        shared = get_shared_connection()
        if shared is not None:
            return
        get_engine().connect().close()


class _ConnectionHandler:
    """``connections['default']`` -- the alias-to-connection accessor.

    ``__getitem__`` consults the instance dictionary before doing any work
    so that replacing it with ``mock.patch('app.db.connections.__getitem__')``
    takes effect: patching installs the replacement as an *instance*
    attribute, while subscription is resolved on the type, so without this
    indirection the patch would be invisible.
    """

    def __getitem__(self, alias: str) -> Any:
        override = self.__dict__.get('__getitem__')
        if override is not None:
            return override(alias)
        return self.connect(alias)

    def connect(self, alias: str = 'default') -> _Connection:
        if alias not in settings.DATABASES:
            raise KeyError(alias)
        return _Connection(alias)


#: Process-wide alias registry, mirroring ``settings.DATABASES``.
connections = _ConnectionHandler()
