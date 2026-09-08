"""Home page sliders."""
from __future__ import annotations

import datetime as _datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app import settings
from app.db import BIG_PK, Base
from app.text import slugify
from core.models.manager import Manager, MultipleObjectsReturned, ObjectDoesNotExist
from core.models.model_support import utcnow


def slider_image_file_path(instance, filename):
    f_name, ext = filename.split('.')
    allowed_chars = \
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._"
    sanitized_filename = ''.join(c for c in f_name if c in allowed_chars)
    slug = slugify(sanitized_filename)
    # IMAGE_ROOT already ends in a separator, so the joined path carries a
    # doubled slash. Kept as-is: stored paths in the database have that shape.
    file_path = f'{settings.IMAGE_ROOT}/{slug}.{ext}'
    return file_path


class Slider(Base):
    __tablename__ = 'core_slider'

    DoesNotExist = type('DoesNotExist', (ObjectDoesNotExist,), {})
    MultipleObjectsReturned = type('MultipleObjectsReturned', (MultipleObjectsReturned,), {})
    objects = Manager()

    id: Mapped[int] = mapped_column(BIG_PK, primary_key=True, autoincrement=True)
    created_at: Mapped[_datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[_datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, default='')
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    link: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    image: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_delete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    user_id: Mapped[Optional[int]] = mapped_column(
        BIG_PK, ForeignKey('core_user.id', ondelete='SET NULL'), nullable=True
    )
    approval_user_id: Mapped[Optional[int]] = mapped_column(
        BIG_PK, ForeignKey('core_user.id', ondelete='SET NULL'), nullable=True
    )

    user = relationship('User', foreign_keys=[user_id], lazy='joined')
    approval_user = relationship('User', foreign_keys=[approval_user_id], lazy='joined')

    @property
    def pk(self):
        return self.id

    def save(self, session=None):
        from app import db as _db

        session = session or _db.get_session()
        if self.created_at is None:
            self.created_at = utcnow()
        if self.updated_at is None:
            self.updated_at = utcnow()
        session.add(self)
        session.flush()
        return self

    @property
    def image_url(self):
        if self.image:
            return str(self.image).replace(settings.APLICATION_NAME, '')
        return None

    def __str__(self) -> str:
        return self.title
