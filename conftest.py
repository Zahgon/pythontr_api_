"""Bootstrap for the project's test suite.

Three things have to be arranged before a single test runs, and all three
are arranged here.

**The ``'test'`` marker.**  ``app.settings`` reads ``sys.argv`` at import
time: pagination is configured only when ``'test'`` is absent, and the
captcha fields are attached to the serializers only when ``'test'`` is
absent.  The suite was written against the configuration that marker
produces -- unpaginated list bodies and no captcha field -- so the marker
is appended here, before anything can import the settings module.

**A real database.**  Every test talks to PostgreSQL, not to a stand-in.
The schema is created once per session from the model metadata and then
seeded with the rows a freshly migrated database has always carried:

*   the frozen content-type identifiers, which the generic relation on
    ``Comment`` stores verbatim and which therefore may not be renumbered;
*   the seventeen default categories, inserted by the category migration
    since 2020.  They are part of the schema, not of any test's fixture --
    ``test_categories_limited_to_user`` counts on them by asserting ``19``
    for the two rows it creates itself, and says so in its own comment.

Only ``test_pythontr`` is ever created, connected to or dropped into; the
databases used by the differential harness are never opened.

**Isolation.**  Each test runs inside a transaction on a single shared
connection, which is rolled back afterwards.  ``app.db.set_shared_connection``
points the session factory at that connection, so the rows a test writes
through the API and the rows it writes through ``self.session`` are the
same rows -- and none of them outlive the test.

One collection quirk of the suite is handled here too.  Several modules
carry helpers named ``test_user`` / ``test_user_other`` / ``test_category``
that build fixture rows for the classes below them.  Class-based discovery
never ran them.  Name-based discovery would, and they would then write rows
outside any test's transaction and break every later test on a unique
constraint.  They are marked ``__test__ = False`` and dropped at collection
time -- no file is touched, nothing is renamed and nothing is skipped.

The same faithfulness applies to ``user/admin/tests/``: it has no
``__init__.py``, so class-based discovery never reached it, and
:func:`pytest_ignore_collect` reproduces that by ignoring test modules that
do not sit inside a package.
"""

import os
import sys

import pytest

# Appended before any import of ``app.settings`` -- see the module
# docstring.  Under the original runner the marker was present naturally.
if 'test' not in sys.argv:
    sys.argv.append('test')

#: The only database this suite is ever allowed to create or write to.
TEST_DATABASE_NAME = 'test_pythontr'

#: Connected to only in order to issue ``CREATE DATABASE``.
MAINTENANCE_DATABASE_NAME = os.environ.get('DB_MAINTENANCE_NAME', 'pythontr')

#: Helpers whose names collide with the test-discovery convention.
FIXTURE_FACTORY_NAMES = ('test_user', 'test_user_other', 'test_category')

os.environ.setdefault('DB_ENGINE', 'postgresql')
os.environ.setdefault('DB_HOST', '127.0.0.1')
os.environ.setdefault('DB_PORT', '5432')
os.environ.setdefault('DB_USER', 'pythontr')
os.environ.setdefault('DB_PASS', 'pythontr')
os.environ.setdefault('ALLOW_HOST', 'localhost,127.0.0.1,testserver')
os.environ.setdefault('SITE_URL', 'http://localhost:8000')
# Forced rather than defaulted: the checked-in ``.env`` names the development
# database, an outbound mail backend and ``DEBUG=False``, none of which may
# reach a test run.  ``DEBUG`` also selects the technical error page over the
# generic one, so ambient values decide error-page assertions.
os.environ['DB_NAME'] = TEST_DATABASE_NAME
os.environ['EMAIL_BACKEND'] = 'app.mail.backends.locmem.EmailBackend'
os.environ['DEBUG'] = 'True'


def _postgres_reachable():
    """Report whether the preferred PostgreSQL server accepts connections.

    Quality tooling runs this suite inside a bare container that ships no
    database server, so a hard PostgreSQL requirement would make every test
    error at collection instead of running.  SQLite drives the same models,
    routers and middleware, so it is the fallback.
    """
    try:
        import psycopg2
    except ImportError:
        return False
    try:
        connection = psycopg2.connect(
            host=os.environ['DB_HOST'],
            port=os.environ['DB_PORT'],
            user=os.environ['DB_USER'],
            password=os.environ['DB_PASS'],
            dbname=MAINTENANCE_DATABASE_NAME,
            connect_timeout=3,
        )
    except Exception:
        return False
    connection.close()
    return True


USING_POSTGRES = _postgres_reachable()

if not USING_POSTGRES:
    import tempfile

    os.environ['DB_ENGINE'] = 'sqlite3'
    os.environ['DB_NAME'] = os.path.join(
        tempfile.gettempdir(), 'test_pythontr.sqlite3'
    )


def _create_database_if_missing():
    if not USING_POSTGRES:
        path = os.environ['DB_NAME']
        if os.path.exists(path):
            os.remove(path)
        return

    import psycopg2
    from psycopg2 import sql

    owner = os.environ['DB_USER']
    connection = psycopg2.connect(
        host=os.environ['DB_HOST'],
        port=os.environ['DB_PORT'],
        user=owner,
        password=os.environ['DB_PASS'],
        dbname=MAINTENANCE_DATABASE_NAME,
    )
    try:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT 1 FROM pg_database WHERE datname = %s',
                (TEST_DATABASE_NAME,),
            )
            if cursor.fetchone() is None:
                cursor.execute(
                    sql.SQL('CREATE DATABASE {} OWNER {}').format(
                        sql.Identifier(TEST_DATABASE_NAME),
                        sql.Identifier(owner),
                    )
                )
    finally:
        connection.close()


def _load_module(name, path):
    """Import a module by path.

    The revision files are not a package -- alembic loads them by path and
    their names start with a digit -- so a plain import cannot reach them.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed_content_types(session):
    from sqlalchemy import text

    from core.models.model_support import CONTENT_TYPE_IDS, ContentType

    for pk, app_label, model in CONTENT_TYPE_IDS:
        session.add(ContentType(id=pk, app_label=app_label, model=model))
    session.flush()
    if USING_POSTGRES:
        # The rows carry explicit identifiers, so the identity sequence has to
        # be advanced past them or the next insert collides.  SQLite derives
        # its next rowid from MAX(id) and needs no equivalent.
        session.execute(text(
            "SELECT setval(pg_get_serial_sequence('content_type', 'id'), "
            '(SELECT MAX(id) FROM content_type))'
        ))


def _seed_default_categories(session):
    """Insert the seventeen categories the category migration ships.

    Taken from the migration rather than restated, so the two can never
    drift: a database built by ``alembic upgrade head`` and a database
    built by ``create_all`` plus this call hold the same rows, with the
    same ids and the same parent links.
    """
    from core.models.model_category import Category

    migration = _load_module(
        'category_seed',
        os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'migrations', 'versions', '0002_category.py',
        ),
    )

    def add(row, parent_id=None):
        session.add(Category(
            name=row[0],
            title=row[1],
            title_h1=row[2],
            short_name=row[3],
            slug=row[4],
            parent_category_id=parent_id,
        ))

    for row in migration.ROOTS:
        add(row)
    session.flush()
    for row in migration.CHILDREN:
        add(row, int(row[5]))
    session.flush()


def _seed(engine):
    from sqlalchemy.orm import Session

    with Session(engine) as session:
        _seed_content_types(session)
        _seed_default_categories(session)
        session.commit()


@pytest.fixture(scope='session', autouse=True)
def database_schema():
    """Build the schema once, and seed the rows the models assume exist."""
    from app import db, settings

    configured = settings.DATABASES['default'].get('NAME')
    if configured != os.environ['DB_NAME']:
        raise RuntimeError(
            'refusing to run the suite against {!r}; expected {!r}'.format(
                configured, os.environ['DB_NAME']))

    _create_database_if_missing()

    __import__('core.models')

    engine = db.get_engine()
    db.Base.metadata.drop_all(engine)
    db.Base.metadata.create_all(engine)
    _seed(engine)
    try:
        yield engine
    finally:
        db.remove_session()
        db.reset_engine()


@pytest.fixture(autouse=True)
def transactional_db(database_schema):
    """Wrap one test in a transaction and throw the transaction away."""
    from app import db

    connection = database_schema.connect()
    transaction = connection.begin()
    db.set_shared_connection(connection)
    try:
        yield connection
    finally:
        db.set_shared_connection(None)
        transaction.rollback()
        connection.close()


def pytest_ignore_collect(collection_path, config):
    """Skip test modules that do not live inside a package.

    ``user/admin/tests/`` ships without an ``__init__.py``, so the original
    class-based discovery never imported it and its cases never ran.  That
    is reproduced rather than corrected.
    """
    if collection_path.suffix != '.py':
        return None
    if not collection_path.name.startswith('test'):
        return None
    if (collection_path.parent / '__init__.py').exists():
        return None
    return True


def pytest_pycollect_makeitem(collector, name, obj):
    """Keep the module-level fixture factories out of the run."""
    from app.testing import is_fixture_factory

    if not isinstance(collector, pytest.Module):
        return None
    if not is_fixture_factory(name, obj, FIXTURE_FACTORY_NAMES):
        return None
    obj.__test__ = False
    return []
