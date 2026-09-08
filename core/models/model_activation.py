"""One-shot codes e-mailed to a user so they can activate their account."""
from __future__ import annotations

import datetime as _datetime
import uuid as _uuid
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import CHAR, TypeDecorator
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from app.db import BIG_PK, Base
from core.models.manager import Manager, MultipleObjectsReturned, ObjectDoesNotExist
from core.models.model_support import utcnow

ACTIVATION_CODE_LIFETIME = _datetime.timedelta(hours=24)


class GUID(TypeDecorator):
    """``uuid`` on PostgreSQL, 36-character text elsewhere."""

    impl = CHAR(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, _uuid.UUID):
            value = _uuid.UUID(str(value))
        if dialect.name == 'postgresql':
            return value
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, _uuid.UUID):
            return value
        return _uuid.UUID(str(value))


class ActivationCode(Base):
    __tablename__ = 'core_activationcode'

    DoesNotExist = type('DoesNotExist', (ObjectDoesNotExist,), {})
    MultipleObjectsReturned = type(
        'ActivationCodeMultipleObjectsReturned', (MultipleObjectsReturned,), {}
    )
    objects = Manager()

    id: Mapped[int] = mapped_column(BIG_PK, primary_key=True, autoincrement=True)
    code: Mapped[_uuid.UUID] = mapped_column(GUID, nullable=False, default=_uuid.uuid4)
    created_at: Mapped[_datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    expires_at: Mapped[_datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    user_id: Mapped[int] = mapped_column(
        BIG_PK, ForeignKey('core_user.id', ondelete='CASCADE'), nullable=False
    )

    user = relationship('User', lazy='joined')

    @property
    def pk(self):
        return self.id

    def save(self, session=None):
        from app import db as _db

        session = session or _db.get_session()
        if self.code is None:
            self.code = _uuid.uuid4()
        if self.created_at is None:
            self.created_at = utcnow()
        if not self.expires_at:
            self.expires_at = utcnow() + ACTIVATION_CODE_LIFETIME
        session.add(self)
        session.flush()
        return self

    @property
    def is_expired(self) -> bool:
        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=_datetime.timezone.utc)
        return expires_at < utcnow()

    @classmethod
    def create_activation_code(cls, user, session=None):
        """Retire any outstanding code for ``user`` then issue a fresh one."""
        from app import db as _db

        session = session or _db.get_session()
        outstanding = (
            session.query(cls)
            .filter(cls.user_id == (user.id if hasattr(user, 'id') else user), cls.is_used.is_(False))
            .all()
        )
        for code in outstanding:
            code.is_used = True
            session.add(code)
        session.flush()

        activation = cls(
            user_id=user.id if hasattr(user, 'id') else user,
            code=_uuid.uuid4(),
            expires_at=utcnow() + ACTIVATION_CODE_LIFETIME,
            is_used=False,
        )
        return activation.save(session=session)

    def __str__(self) -> str:
        return str(self.code)
