"""Articles and their many-to-many link to categories."""
from __future__ import annotations

import datetime as _datetime
import os
import shutil
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app import settings
from app.db import BIG_PK, Base
from app.text import slugify
from core.models.manager import Manager, MultipleObjectsReturned, ObjectDoesNotExist
from core.models.model_support import utcnow


def article_image_file_path(instance, filename):
    f_name, ext = filename.split('.')
    allowed_chars = \
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._"
    sanitized_filename = ''.join(c for c in f_name if c in allowed_chars)
    slug = slugify(sanitized_filename)
    folder = instance.pk if instance.pk else 'temp'
    file_path = f'{settings.ARTICLE_ROOT}{folder}/{slug}.{ext}'
    return file_path


core_article_categories = Table(
    'core_article_categories',
    Base.metadata,
    Column('id', BIG_PK, primary_key=True, autoincrement=True),
    Column('article_id', BIG_PK, ForeignKey('core_article.id', ondelete='CASCADE'), nullable=False),
    Column(
        'category_id', BIG_PK, ForeignKey('core_category.id', ondelete='CASCADE'), nullable=False
    ),
    UniqueConstraint('article_id', 'category_id', name='core_article_categories_article_id_category_id_uniq'),
)


class Article(Base):
    __tablename__ = 'core_article'

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
    title_h1: Mapped[str] = mapped_column(String(255), nullable=False, default='')
    description: Mapped[str] = mapped_column(Text, nullable=False, default='')
    content: Mapped[str] = mapped_column(Text, nullable=False, default='')
    image: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    read_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    slug: Mapped[str] = mapped_column(String(150), nullable=False, unique=True, default='')
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_delete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    user_id: Mapped[Optional[int]] = mapped_column(
        BIG_PK, ForeignKey('core_user.id', ondelete='SET NULL'), nullable=True
    )
    approval_user_id: Mapped[Optional[int]] = mapped_column(
        BIG_PK, ForeignKey('core_user.id', ondelete='SET NULL'), nullable=True
    )

    categories: Mapped[List['Category']] = relationship(  # noqa: F821
        'Category', secondary=core_article_categories, lazy='selectin'
    )
    user = relationship('User', foreign_keys=[user_id], lazy='joined')
    approval_user = relationship('User', foreign_keys=[approval_user_id], lazy='joined')

    @property
    def pk(self):
        return self.id

    def get_slug(self, session=None):
        from app import db as _db

        session = session or _db.get_session()
        slug = slugify(str(self.title_h1).replace('ı', 'i'))
        base_slug = slug
        counter = 1
        while (
            session.query(Article).filter(Article.slug == slug).first()
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

        if self.image and 'temp' in str(self.image):
            old_path = str(self.image)
            filename = os.path.basename(old_path)
            new_path = f'{settings.ARTICLE_ROOT}{self.pk}/{filename}'
            absolute_old = os.path.join(settings.BASE_DIR, old_path)
            absolute_new = os.path.join(settings.BASE_DIR, new_path)
            if os.path.exists(absolute_old):
                os.makedirs(os.path.dirname(absolute_new), exist_ok=True)
                shutil.move(absolute_old, absolute_new)
            self.image = new_path
            session.add(self)
            session.flush()
        return self

    @property
    def image_url(self):
        if self.image:
            return str(self.image).replace(settings.APLICATION_NAME, '')
        return None

    @property
    def comments(self):
        """Comments attached to this article through the generic relation."""
        from app import db as _db
        from core.models.model_comment import Comment
        from core.models.model_support import ARTICLE_CONTENT_TYPE_ID

        session = _db.get_session()
        return (
            session.query(Comment)
            .filter(
                Comment.content_type_id == ARTICLE_CONTENT_TYPE_ID,
                Comment.object_id == self.id,
            )
            .all()
        )

    def __str__(self) -> str:
        return self.title
