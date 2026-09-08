"""Article categories, arranged as a self-referencing tree."""
from __future__ import annotations

import datetime as _datetime
from typing import List, Optional

from sqlalchemy import DateTime, ForeignKey, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import BIG_PK, Base
from app.text import slugify
from core.models.manager import Manager, MultipleObjectsReturned, ObjectDoesNotExist
from core.models.model_support import utcnow


class Category(Base):
    __tablename__ = 'core_category'

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
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, default='')
    title: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, default='')
    title_h1: Mapped[str] = mapped_column(String(255), nullable=False, default='')
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    short_name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, default='')
    slug: Mapped[str] = mapped_column(String(150), nullable=False, unique=True, default='')
    sort: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True, default=0)
    parent_category_id: Mapped[Optional[int]] = mapped_column(
        BIG_PK, ForeignKey('core_category.id', ondelete='SET NULL'), nullable=True
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        BIG_PK, ForeignKey('core_user.id', ondelete='SET NULL'), nullable=True
    )

    parent_category: Mapped[Optional['Category']] = relationship(
        'Category', remote_side='Category.id', back_populates='category_set', lazy='joined',
        join_depth=4,
    )
    category_set: Mapped[List['Category']] = relationship(
        'Category', back_populates='parent_category', lazy='selectin',
    )
    user = relationship('User', lazy='joined')

    @property
    def pk(self):
        return self.id

    def get_slug(self, session=None):
        from app import db as _db

        session = session or _db.get_session()
        slug = slugify(str(self.name).replace('ı', 'i'))
        base_slug = slug
        counter = 1
        while (
            session.query(Category)
            .filter(Category.slug == slug)
            .first()
            is not None
        ):
            slug = '{}-{}'.format(base_slug, counter)
            counter += 1
        return slug

    def save(self, session=None):
        from app import db as _db

        session = session or _db.get_session()
        if not self.title_h1:
            self.title_h1 = self.title
        if self.created_at is None:
            self.created_at = utcnow()
        self.updated_at = utcnow()
        self.slug = self.get_slug(session=session)
        session.add(self)
        session.flush()
        return self

    @property
    def full_category_name(self) -> str:
        names = []
        node = self
        seen = set()
        while node is not None and id(node) not in seen:
            seen.add(id(node))
            names.append(node.name)
            node = node.parent_category
        return ' / '.join(reversed(names))

    def __str__(self) -> str:
        return self.full_category_name

    def __unicode__(self) -> str:
        return self.full_category_name
