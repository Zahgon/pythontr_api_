"""slider

Revision ID: 0007_slider
Revises: 0006_auto_20230818_2043
"""
from alembic import op
import sqlalchemy as sa

revision = '0007_slider'
down_revision = '0006_auto_20230818_2043'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'core_slider',
        sa.Column('id',
                  sa.BigInteger().with_variant(sa.Integer(), 'sqlite'),
                  sa.Identity(always=False),
                  primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False, unique=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('link', sa.String(length=255), nullable=True),
        sa.Column('image', sa.String(length=100), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('is_approval', sa.Boolean(), nullable=False),
        sa.Column('is_delete', sa.Boolean(), nullable=False),
        sa.Column('approval_user_id', sa.BigInteger(), nullable=True),
        sa.Column('user_id', sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(['approval_user_id'], ['core_user.id'],
                                name='core_slider_approval_user_id_fk',
                                deferrable=True, initially='DEFERRED'),
        sa.ForeignKeyConstraint(['user_id'], ['core_user.id'],
                                name='core_slider_user_id_fk',
                                deferrable=True, initially='DEFERRED'),
    )
    op.create_index('core_slider_approval_user_id', 'core_slider',
                    ['approval_user_id'])
    op.create_index('core_slider_user_id', 'core_slider', ['user_id'])


def downgrade():
    op.drop_table('core_slider')
