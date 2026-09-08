"""category

Creates the category table and seeds the seventeen categories the site has
always shipped with.  The seed is the same list, in the same order, with the
same parent links, so the generated ids stay 1..17 and the category listing
endpoint keeps returning ``count == 17`` on a fresh database.

The project's migration also re-declared ``User.image`` to change its
``upload_to`` callback.  That is a Python-level attribute with no column
counterpart, so it produces no DDL here either.

Revision ID: 0002_category
Revises: 0001_initial
"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa

revision = '0002_category'
down_revision = '0001_initial'
branch_labels = None
depends_on = None

INSERT_ROOT = sa.text(
    'INSERT INTO core_category '
    '(name, title, title_h1, short_name, slug, created_at, updated_at) '
    'VALUES (:name, :title, :title_h1, :short_name, :slug, '
    ':created_at, :updated_at)'
)

INSERT_CHILD = sa.text(
    'INSERT INTO core_category '
    '(name, title, title_h1, short_name, slug, created_at, updated_at, '
    'parent_category_id) '
    'VALUES (:name, :title, :title_h1, :short_name, :slug, '
    ':created_at, :updated_at, :parent_category_id)'
)

ROOTS = [
    ['Programlama', 'Programlama Dilleri',
     'Programlama Dilleri Hakkında', 'Programlama', 'programlama'],
    ['Veritabanı', 'Veritabanları',
     'Veritabanları Hakkında', 'Veritabanı', 'veritabani'],
    ['Sistemler / Dağıtımlar', 'Sistemler ve Dağıtımlar',
     'İşletim sistemleri ve dağıtımlar hakkında', 'Sistemler',
     'sistemler-dagitimlar'],
    ['Haberler', 'Teknoloji Haberleri',
     'Teknoloji haberleri hakkında', 'teknoloji', 'teknoloji-haberleri'],
]

CHILDREN = [
    ['Python', 'Python Programlama Dili',
     'Python Programlama Dili Hakkında', 'Python', 'python', '1'],
    ['Php', 'Php Programlama Dili',
     'Php Programlama Dili Hakkında', 'Php', 'php', '1'],
    ['Go', 'Go Programlama Dili',
     'Go Programlama Dili Hakkında', 'Go', 'go', '1'],
    ['C#', 'C# Programlama Dili',
     'C# Programlama Dili Hakkında', 'C#', 'c-sharp', '1'],
    ['Java Script', 'Java Script Programlama Dili',
     'Java Script Programlama Frameworkleri', 'Java Script', 'javascript',
     '1'],
    ['Mobil Programlama', 'Mobil Programlama Dilleri',
     'Mobil Programlama', 'Mobil Programlama', 'mobil', '1'],
    ['MySql / MariaDb', 'MySql ve MariaDb veritabanları',
     'MySql ve MariaDb Veritabanları Hakkında', 'MySql / MariaDb',
     'mysql-mariadb', '2'],
    ['MsSql', 'MsSql Veritabanı',
     'MsSql Veritabanı Hakkında', 'MsSql', 'mssql', '2'],
    ['PostgreSql', 'PostgreSql Veritabanı',
     'PostgreSql Veritabanı Hakkında', 'PostgreSql', 'postgresql', '2'],
    ['Oracle', 'Oracle Veritabanı',
     'Oracle Veritabanı Hakkında', 'Oracle', 'oracle', '2'],
    ['Linux', 'Linux İşletim Sistemleri',
     'Debian \\ Ubuntu \\ Pardus vb', 'Linux', 'linux', '3'],
    ['OS', 'MacOs ve Ios',
     'MacOs ve Ios İşletim Sistemleri', 'macos', 'macos-ios', '3'],
    ['Windows X', 'Windows İşletim Sistemleri',
     'Windows İşletim Sistemi', 'Windows', 'windows', '3'],
]


def upgrade():
    op.create_table(
        'core_category',
        sa.Column('id', sa.Integer(), sa.Identity(always=False),
                  primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False, unique=True),
        sa.Column('title', sa.String(length=255), nullable=False, unique=True),
        sa.Column('title_h1', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('short_name', sa.String(length=100), nullable=False,
                  unique=True),
        sa.Column('slug', sa.String(length=150), nullable=False, unique=True),
        sa.Column('sort', sa.SmallInteger(), nullable=True),
        sa.Column('parent_category_id', sa.Integer(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['parent_category_id'], ['core_category.id'],
                                name='core_category_parent_category_id_fk',
                                deferrable=True, initially='DEFERRED'),
        sa.ForeignKeyConstraint(['user_id'], ['core_user.id'],
                                name='core_category_user_id_fk',
                                deferrable=True, initially='DEFERRED'),
    )
    op.create_index('core_category_parent_category_id', 'core_category',
                    ['parent_category_id'])
    op.create_index('core_category_user_id', 'core_category', ['user_id'])

    connection = op.get_bind()
    for row in ROOTS:
        connection.execute(INSERT_ROOT, {
            'name': row[0], 'title': row[1], 'title_h1': row[2],
            'short_name': row[3], 'slug': row[4],
            'created_at': datetime.now(), 'updated_at': datetime.now(),
        })
    for row in CHILDREN:
        connection.execute(INSERT_CHILD, {
            'name': row[0], 'title': row[1], 'title_h1': row[2],
            'short_name': row[3], 'slug': row[4],
            'created_at': datetime.now(), 'updated_at': datetime.now(),
            'parent_category_id': row[5],
        })


def downgrade():
    op.drop_table('core_category')
