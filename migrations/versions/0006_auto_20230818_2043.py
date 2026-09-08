"""auto_20230818_2043

Adds the article image column and widens every primary key that was still a
32-bit ``AutoField`` to 64 bits, together with the foreign keys that point at
them.  Postgres will not widen a referenced key on its own, so each
referencing column is altered in the same step.  SQLite stores every INTEGER
PRIMARY KEY as a 64-bit rowid and has no ALTER COLUMN TYPE, so the widening is
already true there and is skipped.

Revision ID: 0006_auto_20230818_2043
Revises: 0005_message
"""
from alembic import op
import sqlalchemy as sa

revision = '0006_auto_20230818_2043'
down_revision = '0005_message'
branch_labels = None
depends_on = None

WIDENED = [
    ('core_article', 'id'),
    ('core_article', 'approval_user_id'),
    ('core_article', 'user_id'),
    ('core_article_categories', 'article_id'),
    ('core_article_categories', 'category_id'),
    ('core_category', 'id'),
    ('core_category', 'parent_category_id'),
    ('core_category', 'user_id'),
    ('core_comment', 'id'),
    ('core_comment', 'user_id'),
    ('core_message', 'id'),
    ('core_message', 'sender_id'),
    ('core_message', 'user_id'),
    ('core_user', 'id'),
    ('core_user_groups', 'user_id'),
    ('core_user_user_permissions', 'user_id'),
    ('admin_log', 'user_id'),
    ('authtoken_token', 'user_id'),
]


def upgrade():
    op.add_column('core_article',
                  sa.Column('image', sa.String(length=100), nullable=True))
    if op.get_bind().dialect.name != 'postgresql':
        return
    # The category seed in 0002 leaves deferred foreign-key trigger events
    # queued in this transaction, and Postgres refuses to ALTER a table that
    # has any pending. Flush them before widening the keys.
    op.execute('SET CONSTRAINTS ALL IMMEDIATE')
    for table, column in WIDENED:
        op.alter_column(table, column, type_=sa.BigInteger())


def downgrade():
    if op.get_bind().dialect.name == 'postgresql':
        for table, column in reversed(WIDENED):
            op.alter_column(table, column, type_=sa.Integer())
    op.drop_column('core_article', 'image')
