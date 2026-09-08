"""article

Revision ID: 0003_article
Revises: 0002_category
"""
from alembic import op
import sqlalchemy as sa

revision = '0003_article'
down_revision = '0002_category'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'core_article',
        sa.Column('id', sa.Integer(), sa.Identity(always=False),
                  primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False, unique=True),
        sa.Column('title_h1', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('read_count', sa.Integer(), nullable=False),
        sa.Column('slug', sa.String(length=150), nullable=False, unique=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('is_approval', sa.Boolean(), nullable=False),
        sa.Column('is_delete', sa.Boolean(), nullable=False),
        sa.Column('approval_user_id', sa.Integer(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['approval_user_id'], ['core_user.id'],
                                name='core_article_approval_user_id_fk',
                                deferrable=True, initially='DEFERRED'),
        sa.ForeignKeyConstraint(['user_id'], ['core_user.id'],
                                name='core_article_user_id_fk',
                                deferrable=True, initially='DEFERRED'),
    )
    op.create_index('core_article_approval_user_id', 'core_article',
                    ['approval_user_id'])
    op.create_index('core_article_user_id', 'core_article', ['user_id'])
    op.create_table(
        'core_article_categories',
        sa.Column('id',
                  sa.BigInteger().with_variant(sa.Integer(), 'sqlite'),
                  sa.Identity(always=False),
                  primary_key=True),
        sa.Column('article_id', sa.Integer(), nullable=False),
        sa.Column('category_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['article_id'], ['core_article.id'],
                                name='core_article_categories_article_id_fk',
                                deferrable=True, initially='DEFERRED'),
        sa.ForeignKeyConstraint(['category_id'], ['core_category.id'],
                                name='core_article_categories_category_id_fk',
                                deferrable=True, initially='DEFERRED'),
        sa.UniqueConstraint('article_id', 'category_id',
                            name='core_article_categories_article_id_category_id_uniq'),
    )
    op.create_index('core_article_categories_article_id',
                    'core_article_categories', ['article_id'])
    op.create_index('core_article_categories_category_id',
                    'core_article_categories', ['category_id'])


def downgrade():
    op.drop_table('core_article_categories')
    op.drop_table('core_article')
