"""Supporting tables that the application relies on but does not expose.

These mirror the auxiliary tables present in the production database:
content types (used by the generic relation on ``Comment``), auth tokens,
groups/permissions, the admin action log and the server-side session store.
"""
from __future__ import annotations

import datetime as _datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import BIG_PK, Base
from core.models.manager import Manager, ObjectDoesNotExist, MultipleObjectsReturned


def utcnow() -> _datetime.datetime:
    return _datetime.datetime.now(_datetime.timezone.utc)


auth_group_permissions = Table(
    'auth_group_permissions',
    Base.metadata,
    Column('id', BIG_PK, primary_key=True, autoincrement=True),
    Column('group_id', Integer, ForeignKey('auth_group.id', ondelete='CASCADE'), nullable=False),
    Column(
        'permission_id',
        Integer,
        ForeignKey('auth_permission.id', ondelete='CASCADE'),
        nullable=False,
    ),
    UniqueConstraint('group_id', 'permission_id', name='auth_group_permissions_group_id_permission_id_uniq'),
)

core_user_groups = Table(
    'core_user_groups',
    Base.metadata,
    Column('id', BIG_PK, primary_key=True, autoincrement=True),
    Column('user_id', BIG_PK, ForeignKey('core_user.id', ondelete='CASCADE'), nullable=False),
    Column('group_id', Integer, ForeignKey('auth_group.id', ondelete='CASCADE'), nullable=False),
    UniqueConstraint('user_id', 'group_id', name='core_user_groups_user_id_group_id_uniq'),
)

core_user_user_permissions = Table(
    'core_user_user_permissions',
    Base.metadata,
    Column('id', BIG_PK, primary_key=True, autoincrement=True),
    Column('user_id', BIG_PK, ForeignKey('core_user.id', ondelete='CASCADE'), nullable=False),
    Column(
        'permission_id',
        Integer,
        ForeignKey('auth_permission.id', ondelete='CASCADE'),
        nullable=False,
    ),
    UniqueConstraint(
        'user_id', 'permission_id', name='core_user_user_permissions_user_id_permission_id_uniq'
    ),
)


class ContentType(Base):
    """Identifies a model so a generic relation can point at any row."""

    __tablename__ = 'content_type'
    __table_args__ = (UniqueConstraint('app_label', 'model', name='content_type_app_label_model_uniq'),)

    DoesNotExist = type('DoesNotExist', (ObjectDoesNotExist,), {})
    MultipleObjectsReturned = type(
        'ContentTypeMultipleObjectsReturned', (MultipleObjectsReturned,), {}
    )
    objects = Manager()

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    app_label: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)

    def __str__(self) -> str:
        return self.model

    @property
    def name(self) -> str:
        return self.model


class Permission(Base):
    __tablename__ = 'auth_permission'
    __table_args__ = (
        UniqueConstraint('content_type_id', 'codename', name='auth_permission_content_type_id_codename_uniq'),
    )

    DoesNotExist = type('DoesNotExist', (ObjectDoesNotExist,), {})
    MultipleObjectsReturned = type('MultipleObjectsReturned', (MultipleObjectsReturned,), {})
    objects = Manager()

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('content_type.id', ondelete='CASCADE'), nullable=False
    )
    codename: Mapped[str] = mapped_column(String(100), nullable=False)

    content_type: Mapped[ContentType] = relationship(ContentType, lazy='joined')

    def __str__(self) -> str:
        return '%s | %s' % (self.content_type.app_label if self.content_type else '', self.name)


class Group(Base):
    __tablename__ = 'auth_group'

    DoesNotExist = type('DoesNotExist', (ObjectDoesNotExist,), {})
    MultipleObjectsReturned = type('MultipleObjectsReturned', (MultipleObjectsReturned,), {})
    objects = Manager()

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False, unique=True)

    permissions: Mapped[List[Permission]] = relationship(
        Permission, secondary=auth_group_permissions, lazy='selectin'
    )

    def __str__(self) -> str:
        return self.name


class Token(Base):
    """API access token. The key itself is the primary key, as in the source."""

    __tablename__ = 'authtoken_token'

    DoesNotExist = type('DoesNotExist', (ObjectDoesNotExist,), {})
    MultipleObjectsReturned = type('MultipleObjectsReturned', (MultipleObjectsReturned,), {})
    objects = Manager()

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    created: Mapped[_datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    user_id: Mapped[int] = mapped_column(
        BIG_PK, ForeignKey('core_user.id', ondelete='CASCADE'), nullable=False, unique=True
    )

    user = relationship('User', back_populates='auth_token', lazy='joined')

    def save(self, session=None):
        from app import db as _db

        session = session or _db.get_session()
        if not self.key:
            from app.security import generate_token

            self.key = generate_token()
        if self.created is None:
            self.created = utcnow()
        session.add(self)
        session.flush()
        return self

    def __str__(self) -> str:
        return self.key


class AdminLog(Base):
    """Audit trail written by the administration site."""

    __tablename__ = 'admin_log'

    DoesNotExist = type('DoesNotExist', (ObjectDoesNotExist,), {})
    MultipleObjectsReturned = type('MultipleObjectsReturned', (MultipleObjectsReturned,), {})
    objects = Manager()

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action_time: Mapped[_datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    object_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    object_repr: Mapped[str] = mapped_column(String(200), nullable=False)
    action_flag: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    change_message: Mapped[str] = mapped_column(Text, nullable=False, default='')
    content_type_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey('content_type.id', ondelete='SET NULL'), nullable=True
    )
    user_id: Mapped[int] = mapped_column(
        BIG_PK, ForeignKey('core_user.id', ondelete='CASCADE'), nullable=False
    )

    def __str__(self) -> str:
        return self.object_repr


class WebSession(Base):
    """Server-side session store backing the administration cookie."""

    __tablename__ = 'web_session'

    DoesNotExist = type('DoesNotExist', (ObjectDoesNotExist,), {})
    MultipleObjectsReturned = type('MultipleObjectsReturned', (MultipleObjectsReturned,), {})
    objects = Manager()

    session_key: Mapped[str] = mapped_column(String(40), primary_key=True)
    session_data: Mapped[str] = mapped_column(Text, nullable=False)
    expire_date: Mapped[_datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def is_expired(self) -> bool:
        expires = self.expire_date
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=_datetime.timezone.utc)
        return expires <= utcnow()

    def __str__(self) -> str:
        return self.session_key


#: Frozen content type identifiers. The production database assigned these ids
#: in this order and the generic relation on ``Comment`` stores them verbatim,
#: so they must never be renumbered.
CONTENT_TYPE_IDS = (
    (1, 'admin', 'logentry'),
    (2, 'auth', 'permission'),
    (3, 'auth', 'group'),
    (4, 'contenttypes', 'contenttype'),
    (5, 'sessions', 'session'),
    (6, 'authtoken', 'token'),
    (7, 'authtoken', 'tokenproxy'),
    (8, 'core', 'user'),
    (9, 'core', 'category'),
    (10, 'core', 'article'),
    (11, 'core', 'comment'),
    (12, 'core', 'message'),
    (13, 'core', 'slider'),
    (14, 'core', 'pagevisit'),
    (15, 'core', 'activationcode'),
)

ARTICLE_CONTENT_TYPE_ID = 10
COMMENT_CONTENT_TYPE_ID = 11


def content_type_id_for(model_name: str) -> int:
    """Return the frozen content type id for ``model_name``."""
    for pk, _app_label, model in CONTENT_TYPE_IDS:
        if model == model_name.lower():
            return pk
    raise KeyError(model_name)
