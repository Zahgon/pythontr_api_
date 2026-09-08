"""user_github

Revision ID: 0008_user_github
Revises: 0007_slider
"""
from alembic import op
import sqlalchemy as sa

revision = '0008_user_github'
down_revision = '0007_slider'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('core_user',
                  sa.Column('github', sa.String(length=255), nullable=False,
                            server_default=''))
    # The default only backfills existing rows; SQLite has no ALTER COLUMN and
    # would need a table rebuild to drop it, for no observable difference.
    if op.get_bind().dialect.name == 'postgresql':
        op.alter_column('core_user', 'github', server_default=None)


def downgrade():
    op.drop_column('core_user', 'github')
