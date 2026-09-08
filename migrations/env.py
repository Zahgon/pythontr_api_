"""Alembic environment for the pythontr_api schema.

The schema is the one the project has always had; only four framework-owned
table names changed on the way over: ``admin_log``, ``content_type``,
``schema_migrations`` and ``web_session``.  ``version_table`` is pinned to
``schema_migrations`` so Alembic's own bookkeeping table keeps the project's
naming instead of the default ``alembic_version``.

The ten revisions under ``versions/`` mirror the ten migrations the project
shipped, one for one, seed data included, so a fresh database ends up with the
same schema and reference rows the tests and the probe harness expect.

The connection URL is never hardcoded here: it comes from
:func:`app.db.build_url`, which reads the ``DB_*`` environment settings.
"""
from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from typing import Optional

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.engine import Connection

# ``alembic`` is normally invoked from the project root, but make the import
# work regardless of the caller's working directory.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from app.db import Base, build_url  # noqa: E402
import core.models  # noqa: E402,F401  registers every table on Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

#: Autogenerate compares against the models in ``core.models``; importing the
#: package above is what populates ``Base.metadata`` with all 18 tables.
target_metadata = Base.metadata

#: The project's name for Alembic's bookkeeping table.
VERSION_TABLE = 'schema_migrations'


def get_url() -> str:
    """Return the database URL, preferring an explicitly configured one."""
    url = config.get_main_option('sqlalchemy.url', default=None)
    if url:
        return url
    return build_url()


def _configure(**kwargs) -> None:
    context.configure(
        target_metadata=target_metadata,
        version_table=VERSION_TABLE,
        compare_type=True,
        include_schemas=False,
        **kwargs
    )


def run_migrations_offline() -> None:
    """Emit the migration SQL to stdout without touching a database."""
    _configure(
        url=get_url(),
        literal_binds=True,
        dialect_opts={'paramstyle': 'named'},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run the migrations against a live connection."""
    connection: Optional[Connection] = config.attributes.get('connection')
    if connection is not None:
        _configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
        return

    engine = create_engine(get_url(), future=True)
    try:
        with engine.connect() as conn:
            _configure(connection=conn)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
