"""0001_initial — the user table and the framework-owned tables it hangs off.

Mirrors the project's first migration, which created ``core.User`` together
with its two many-to-many link tables.  That migration depended on the
framework's own ``auth`` migration set, which is not replayed here, so the
tables those migrations owned are created in this revision as well:
``content_type``, ``auth_group``, ``auth_permission``,
``auth_group_permissions``, ``authtoken_token``, ``admin_log`` and
``web_session`` (the last four renamed, per the port's table contract).

``core_user`` is created with a plain ``integer`` primary key exactly as the
original did; revision 0006 widens it to ``bigint``.

The fifteen content-type rows are seeded here with their frozen identifiers.
Application code asserts them (``ARTICLE_CONTENT_TYPE_ID`` is 10,
``COMMENT_CONTENT_TYPE_ID`` is 11) and the generic relation on ``Comment``
stores them verbatim, so they may never be renumbered.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from core.models.model_support import CONTENT_TYPE_IDS

revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None

#: The first free content-type id once the frozen rows are in place.
NEXT_CONTENT_TYPE_ID = 16

content_type_seed = sa.table(
    'content_type',
    sa.column('id', sa.Integer),
    sa.column('app_label', sa.String),
    sa.column('model', sa.String),
)


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == 'postgresql'


def upgrade() -> None:
    op.create_table(
        'content_type',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('app_label', sa.String(length=100), nullable=False),
        sa.Column('model', sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'app_label', 'model', name='content_type_app_label_model_uniq'
        ),
    )
    op.create_table(
        'auth_group',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', name='auth_group_name_key'),
    )
    op.create_table(
        'auth_permission',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('content_type_id', sa.Integer(), nullable=False),
        sa.Column('codename', sa.String(length=100), nullable=False),
        sa.ForeignKeyConstraint(
            ['content_type_id'],
            ['content_type.id'],
            name='auth_permission_content_type_id_fkey',
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'content_type_id',
            'codename',
            name='auth_permission_content_type_id_codename_uniq',
        ),
    )
    op.create_table(
        'auth_group_permissions',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('group_id', sa.Integer(), nullable=False),
        sa.Column('permission_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ['group_id'],
            ['auth_group.id'],
            name='auth_group_permissions_group_id_fkey',
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['permission_id'],
            ['auth_permission.id'],
            name='auth_group_permissions_permission_id_fkey',
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'group_id',
            'permission_id',
            name='auth_group_permissions_group_id_permission_id_uniq',
        ),
    )

    # ``github`` arrives in 0008; the primary key widens in 0006.
    op.create_table(
        'core_user',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('password', sa.String(length=128), nullable=False),
        sa.Column('last_login', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_superuser', sa.Boolean(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('username', sa.String(length=255), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('surname', sa.String(length=255), nullable=False),
        sa.Column('image', sa.String(length=100), nullable=True),
        sa.Column('about_me', sa.Text(), nullable=False),
        sa.Column('linkedin', sa.String(length=255), nullable=False),
        sa.Column('is_notification_email', sa.Boolean(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('is_staff', sa.Boolean(), nullable=False),
        sa.Column('is_ban', sa.Boolean(), nullable=False),
        sa.Column('is_delete', sa.Boolean(), nullable=False),
        sa.Column('slug', sa.String(length=150), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email', name='core_user_email_key'),
        sa.UniqueConstraint('slug', name='core_user_slug_key'),
        sa.UniqueConstraint('username', name='core_user_username_key'),
    )
    op.create_table(
        'core_user_groups',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('group_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ['group_id'],
            ['auth_group.id'],
            name='core_user_groups_group_id_fkey',
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['user_id'],
            ['core_user.id'],
            name='core_user_groups_user_id_fkey',
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'user_id', 'group_id', name='core_user_groups_user_id_group_id_uniq'
        ),
    )
    op.create_table(
        'core_user_user_permissions',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('permission_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ['permission_id'],
            ['auth_permission.id'],
            name='core_user_user_permissions_permission_id_fkey',
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['user_id'],
            ['core_user.id'],
            name='core_user_user_permissions_user_id_fkey',
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'user_id',
            'permission_id',
            name='core_user_user_permissions_user_id_permission_id_uniq',
        ),
    )

    # The token key is the primary key, as in the source schema.
    op.create_table(
        'authtoken_token',
        sa.Column('key', sa.String(length=40), nullable=False),
        sa.Column('created', sa.DateTime(timezone=True), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ['user_id'],
            ['core_user.id'],
            name='authtoken_token_user_id_fkey',
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('key'),
        sa.UniqueConstraint('user_id', name='authtoken_token_user_id_key'),
    )
    op.create_table(
        'admin_log',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('action_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('object_id', sa.Text(), nullable=True),
        sa.Column('object_repr', sa.String(length=200), nullable=False),
        sa.Column('action_flag', sa.SmallInteger(), nullable=False),
        sa.Column('change_message', sa.Text(), nullable=False),
        sa.Column('content_type_id', sa.Integer(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ['content_type_id'],
            ['content_type.id'],
            name='admin_log_content_type_id_fkey',
            ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['user_id'],
            ['core_user.id'],
            name='admin_log_user_id_fkey',
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'web_session',
        sa.Column('session_key', sa.String(length=40), nullable=False),
        sa.Column('session_data', sa.Text(), nullable=False),
        sa.Column('expire_date', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('session_key'),
    )

    op.bulk_insert(
        content_type_seed,
        [
            {'id': pk, 'app_label': app_label, 'model': model}
            for pk, app_label, model in CONTENT_TYPE_IDS
        ],
    )
    if _is_postgresql():
        # The ids above were supplied explicitly, so the backing sequence is
        # still at 1. Move it past the frozen block.
        op.execute(
            'ALTER SEQUENCE content_type_id_seq RESTART WITH {}'.format(
                NEXT_CONTENT_TYPE_ID
            )
        )


def downgrade() -> None:
    op.drop_table('web_session')
    op.drop_table('admin_log')
    op.drop_table('authtoken_token')
    op.drop_table('core_user_user_permissions')
    op.drop_table('core_user_groups')
    op.drop_table('core_user')
    op.drop_table('auth_group_permissions')
    op.drop_table('auth_permission')
    op.drop_table('auth_group')
    op.drop_table('content_type')
