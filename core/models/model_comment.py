"""Comments. A comment points at any row through a content type + object id."""
from __future__ import annotations

import datetime as _datetime
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import BIG_PK, Base
from core.models.manager import Manager, MultipleObjectsReturned, ObjectDoesNotExist
from core.models.model_support import COMMENT_CONTENT_TYPE_ID, ContentType, utcnow


class Comment(Base):
    __tablename__ = 'core_comment'

    DoesNotExist = type('DoesNotExist', (ObjectDoesNotExist,), {})
    MultipleObjectsReturned = type('MultipleObjectsReturned', (MultipleObjectsReturned,), {})
    objects = Manager()

    id: Mapped[int] = mapped_column(BIG_PK, primary_key=True, autoincrement=True)
    content_type_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('content_type.id', ondelete='CASCADE'), nullable=False
    )
    object_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[_datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, default='')
    email: Mapped[str] = mapped_column(String(100), nullable=False, default='')
    name: Mapped[str] = mapped_column(String(50), nullable=False, default='')
    ip: Mapped[str] = mapped_column(String(100), nullable=False, default='')
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_delete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    user_id: Mapped[Optional[int]] = mapped_column(
        BIG_PK, ForeignKey('core_user.id', ondelete='SET NULL'), nullable=True
    )

    content_type: Mapped[ContentType] = relationship(ContentType, lazy='joined')
    user = relationship('User', lazy='joined')

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

    @property
    def content_object(self):
        """Resolve the row this comment is attached to."""
        from app import db as _db
        from core.models.model_article import Article
        from core.models.model_support import ARTICLE_CONTENT_TYPE_ID

        session = _db.get_session()
        if self.content_type_id == ARTICLE_CONTENT_TYPE_ID:
            return session.get(Article, self.object_id)
        if self.content_type_id == COMMENT_CONTENT_TYPE_ID:
            return session.get(Comment, self.object_id)
        return None

    @property
    def comments(self) -> List['Comment']:
        """Replies: comments whose content type is ``comment`` and object id is ours."""
        from app import db as _db

        session = _db.get_session()
        return (
            session.query(Comment)
            .filter(
                Comment.content_type_id == COMMENT_CONTENT_TYPE_ID,
                Comment.object_id == self.id,
            )
            .all()
        )

    def __str__(self) -> str:
        return self.content
