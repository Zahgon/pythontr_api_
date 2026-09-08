"""message

Revision ID: 0005_message
Revises: 0004_comment
"""
from alembic import op
import sqlalchemy as sa

revision = '0005_message'
down_revision = '0004_comment'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'core_message',
        sa.Column('id', sa.Integer(), sa.Identity(always=False),
                  primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('subject', sa.String(length=255), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('ip', sa.String(length=100), nullable=False),
        sa.Column('is_read', sa.Boolean(), nullable=False),
        sa.Column('is_delete', sa.Boolean(), nullable=False),
        sa.Column('is_sender_delete', sa.Boolean(), nullable=False),
        sa.Column('sender_id', sa.Integer(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['sender_id'], ['core_user.id'],
                                name='core_message_sender_id_fk',
                                deferrable=True, initially='DEFERRED'),
        sa.ForeignKeyConstraint(['user_id'], ['core_user.id'],
                                name='core_message_user_id_fk',
                                deferrable=True, initially='DEFERRED'),
    )
    op.create_index('core_message_sender_id', 'core_message', ['sender_id'])
    op.create_index('core_message_user_id', 'core_message', ['user_id'])


def downgrade():
    op.drop_table('core_message')
