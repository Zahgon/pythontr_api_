"""Private messages exchanged between two users."""
from __future__ import annotations

import datetime as _datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import BIG_PK, Base
from core.models.manager import Manager, MultipleObjectsReturned, ObjectDoesNotExist
from core.models.model_support import utcnow


class MessageManager(Manager):
    """Default manager hiding soft-deleted rows."""

    def get_queryset(self):
        return super().get_queryset().filter(is_delete=False)


class Message(Base):
    __tablename__ = 'core_message'

    DoesNotExist = type('DoesNotExist', (ObjectDoesNotExist,), {})
    MultipleObjectsReturned = type('MultipleObjectsReturned', (MultipleObjectsReturned,), {})
    objects = MessageManager()

    id: Mapped[int] = mapped_column(BIG_PK, primary_key=True, autoincrement=True)
    created_at: Mapped[_datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    subject: Mapped[str] = mapped_column(String(255), nullable=False, default='')
    content: Mapped[str] = mapped_column(Text, nullable=False, default='')
    ip: Mapped[str] = mapped_column(String(100), nullable=False, default='')
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_delete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_sender_delete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sender_id: Mapped[Optional[int]] = mapped_column(
        BIG_PK, ForeignKey('core_user.id', ondelete='SET NULL'), nullable=True
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        BIG_PK, ForeignKey('core_user.id', ondelete='SET NULL'), nullable=True
    )

    sender = relationship('User', foreign_keys=[sender_id], lazy='joined')
    user = relationship('User', foreign_keys=[user_id], lazy='joined')

    @property
    def pk(self):
        return self.id

    def save(self, session=None):
        from app import db as _db

        session = session or _db.get_session()
        if self.created_at is None:
            self.created_at = utcnow()
        session.add(self)
        session.flush()
        return self

    def __str__(self) -> str:
        return self.subject
