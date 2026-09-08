"""Analytics rows recorded for every tracked page view."""
from __future__ import annotations

import datetime as _datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.db import BIG_PK, Base
from core.models.manager import Manager, MultipleObjectsReturned, ObjectDoesNotExist
from core.models.model_support import utcnow

METHOD_CHOICES = ('GET', 'POST', 'PUT', 'DELETE', 'PATCH')
DEVICE_TYPE_CHOICES = ('mobile', 'tablet', 'desktop')


class IPAddress(TypeDecorator):
    """``inet`` on PostgreSQL, plain text everywhere else."""

    impl = String(39)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(INET())
        return dialect.type_descriptor(String(39))


class PageVisit(Base):
    __tablename__ = 'core_pagevisit'
    __table_args__ = (
        Index('core_pagevisit_timestamp_idx', 'timestamp'),
        Index('core_pagevisit_device_type_idx', 'device_type'),
        Index('core_pagevisit_ip_address_idx', 'ip_address'),
    )

    DoesNotExist = type('DoesNotExist', (ObjectDoesNotExist,), {})
    MultipleObjectsReturned = type('MultipleObjectsReturned', (MultipleObjectsReturned,), {})
    objects = Manager()

    #: Default ordering applied by list endpoints, newest first.
    ordering = ('-timestamp',)

    id: Mapped[int] = mapped_column(BIG_PK, primary_key=True, autoincrement=True)
    path: Mapped[str] = mapped_column(String(255), nullable=False, default='')
    content_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    timestamp: Mapped[_datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    ip_address: Mapped[Optional[str]] = mapped_column(IPAddress, nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    referrer: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    method: Mapped[str] = mapped_column(String(10), nullable=False, default='GET')
    # The declared choices are mobile/tablet/desktop yet the column default is
    # ``unknown``. Preserved: rows created without an explicit device type carry
    # a value outside the choice list.
    device_type: Mapped[str] = mapped_column(String(50), nullable=False, default='unknown')
    language: Mapped[Optional[str]] = mapped_column(String(10), nullable=True, default='en')
    browser: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    os: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    device_brand: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    device_model: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    ga_client_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    ga_session_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    gads_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    gpi_uid: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        BIG_PK, ForeignKey('core_user.id', ondelete='CASCADE'), nullable=True
    )

    user = relationship('User', lazy='joined')

    @property
    def pk(self):
        return self.id

    def save(self, session=None):
        from app import db as _db

        session = session or _db.get_session()
        if self.timestamp is None:
            self.timestamp = utcnow()
        session.add(self)
        session.flush()
        return self

    def __str__(self) -> str:
        return f"{self.user} visited {self.path} at {self.timestamp}"
