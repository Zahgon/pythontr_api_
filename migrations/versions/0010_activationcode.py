"""activationcode

Revision ID: 0010_activationcode
Revises: 0009_pagevisit
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0010_activationcode'
down_revision = '0009_pagevisit'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'core_activationcode',
        sa.Column('id',
                  sa.BigInteger().with_variant(sa.Integer(), 'sqlite'),
                  sa.Identity(always=False),
                  primary_key=True),
        sa.Column('code', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_used', sa.Boolean(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['core_user.id'],
                                name='core_activationcode_user_id_fk',
                                deferrable=True, initially='DEFERRED'),
    )
    op.create_index('core_activationcode_user_id', 'core_activationcode',
                    ['user_id'])


def downgrade():
    op.drop_table('core_activationcode')
