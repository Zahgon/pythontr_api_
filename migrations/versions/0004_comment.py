"""comment

Revision ID: 0004_comment
Revises: 0003_article
"""
from alembic import op
import sqlalchemy as sa

revision = '0004_comment'
down_revision = '0003_article'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'core_comment',
        sa.Column('id', sa.Integer(), sa.Identity(always=False),
                  primary_key=True),
        sa.Column('object_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('email', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.Column('ip', sa.String(length=100), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('is_delete', sa.Boolean(), nullable=False),
        sa.Column('content_type_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.CheckConstraint('object_id >= 0',
                           name='core_comment_object_id_check'),
        sa.ForeignKeyConstraint(['content_type_id'], ['content_type.id'],
                                name='core_comment_content_type_id_fk',
                                deferrable=True, initially='DEFERRED'),
        sa.ForeignKeyConstraint(['user_id'], ['core_user.id'],
                                name='core_comment_user_id_fk',
                                deferrable=True, initially='DEFERRED'),
    )
    op.create_index('core_comment_content_type_id', 'core_comment',
                    ['content_type_id'])
    op.create_index('core_comment_user_id', 'core_comment', ['user_id'])


def downgrade():
    op.drop_table('core_comment')
