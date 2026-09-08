"""Pydantic schemas and response builders for the recipe endpoints.

Two halves live here:

* Pydantic models validate incoming payloads.  They exist so that a bad
  request is rejected with the project's field-keyed Turkish error body
  rather than the web framework's own validation envelope.
* ``serialize_*`` helpers build the outgoing dictionaries.  They are plain
  functions instead of response models because the key order of every
  document is part of the published contract and a mapping literal is the
  only honest way to pin it down.
"""

from __future__ import annotations

import base64
import binascii
import re
from datetime import datetime, timezone
from typing import Any, ClassVar, Dict, FrozenSet, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.i18n import gettext as _
from app.text import slugify
from app.wire import ValidationFailed
from core.models import ARTICLE_CONTENT_TYPE_ID, COMMENT_CONTENT_TYPE_ID, Comment

_DATA_URL = re.compile(r'^data:(?P<mime>[-\w.+]+/[-\w.+]+);base64,(?P<payload>.*)$', re.DOTALL)


def isoformat(value: Optional[datetime]) -> Optional[str]:
    """Render a timestamp the way the published documents carry it.

    UTC instants end in ``Z``; sub-second precision is only emitted when the
    value actually has it.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    if value.microsecond:
        return value.strftime('%Y-%m-%dT%H:%M:%S.%f') + 'Z'
    return value.strftime('%Y-%m-%dT%H:%M:%SZ')


def _fk(value: Any) -> Optional[int]:
    return None if value is None else int(value)


# ---------------------------------------------------------------------------
# Category
# ---------------------------------------------------------------------------

class CategoryInput(BaseModel):
    """Writable fields of a category, declared in serializer order."""

    model_config = ConfigDict(extra='ignore', str_strip_whitespace=False)
    nullable_fields: ClassVar[FrozenSet[str]] = frozenset({
        'description', 'content', 'parent_category',
    })

    name: str = Field(min_length=1)
    title: str = Field(min_length=1)
    title_h1: str = Field(min_length=1)
    description: Optional[str] = None
    content: Optional[str] = None
    short_name: Optional[str] = None
    parent_category: Optional[int] = None


CATEGORY_INPUT_ORDER = (
    'name', 'title', 'title_h1', 'description', 'content',
    'short_name', 'parent_category',
)


def serialize_category_related(obj: Any) -> Dict[str, Any]:
    return {
        'id': obj.id,
        'parent_category': _fk(obj.parent_category_id),
        'name': obj.name,
        'title': obj.title,
        'title_h1': obj.title_h1,
        'description': obj.description,
        'content': obj.content,
        'slug': obj.slug,
        'short_name': obj.short_name,
        'full_category_name': obj.full_category_name,
        'created_at': isoformat(obj.created_at),
        'updated_at': isoformat(obj.updated_at),
    }


def serialize_category(obj: Any) -> Dict[str, Any]:
    document = serialize_category_related(obj)
    document['categories'] = [serialize_category_related(child) for child in obj.category_set]
    return document


# ---------------------------------------------------------------------------
# Comment
# ---------------------------------------------------------------------------

class CommentInput(BaseModel):
    model_config = ConfigDict(extra='ignore')
    nullable_fields: ClassVar[FrozenSet[str]] = frozenset({'user'})

    content: Optional[str] = None
    email: str = Field(min_length=1)
    name: str = Field(min_length=1)
    ip: str = Field(min_length=1)
    user: Optional[int] = None
    content_type: int
    object_id: int


COMMENT_INPUT_ORDER = ('content', 'email', 'name', 'ip', 'user', 'content_type', 'object_id')


def serialize_comment(obj: Any, session: Any = None) -> Dict[str, Any]:
    replies: List[Any]
    if session is None:
        replies = list(obj.comments)
    else:
        replies = list(
            session.query(Comment)
            .filter(
                Comment.content_type_id == COMMENT_CONTENT_TYPE_ID,
                Comment.object_id == obj.id,
            )
            .all()
        )
    return {
        'id': obj.id,
        'content': obj.content,
        'email': obj.email,
        'name': obj.name,
        'ip': obj.ip,
        'user': _fk(obj.user_id),
        'content_type': obj.content_type_id,
        'object_id': obj.object_id,
        'comments': [serialize_comment(reply, session) for reply in replies],
    }


# ---------------------------------------------------------------------------
# Article
# ---------------------------------------------------------------------------

class ArticleInput(BaseModel):
    model_config = ConfigDict(extra='ignore')
    nullable_fields: ClassVar[FrozenSet[str]] = frozenset({'image'})

    categories: List[int] = Field(min_length=1)
    title: str = Field(min_length=1)
    title_h1: str = Field(min_length=1)
    description: Optional[str] = ''
    content: Optional[str] = ''
    image: Optional[str] = None
    is_active: Optional[bool] = None
    is_approval: Optional[bool] = None
    is_delete: Optional[bool] = None

    @field_validator('categories', mode='before')
    @classmethod
    def _coerce_categories(cls, value: Any) -> Any:
        if value is None:
            return value
        if isinstance(value, (str, int)):
            return [value]
        return value


ARTICLE_INPUT_ORDER = (
    'categories', 'title', 'title_h1', 'description', 'content', 'image',
    'is_active', 'is_approval', 'is_delete',
)


def decode_data_url(payload: Any, title: str) -> Any:
    """Turn an inline ``data:`` image into a (filename, bytes) pair.

    Mirrors the baseline behaviour where a base64 document posted in the
    ``image`` field is written out under a slug of the article title.
    """
    if not isinstance(payload, str):
        return payload
    match = _DATA_URL.match(payload)
    if match is None:
        return payload
    extension = match.group('mime').split('/')[-1]
    try:
        content = base64.b64decode(match.group('payload'))
    except (binascii.Error, ValueError):
        raise ValidationFailed({'image': [_('Enter a valid value.')]})
    name = slugify(title)[:50] or 'temp'
    return ('{}.{}'.format(name, extension), content)


def serialize_article(obj: Any, session: Any = None) -> Dict[str, Any]:
    if session is None:
        comments = list(obj.comments)
    else:
        comments = list(
            session.query(Comment)
            .filter(
                Comment.content_type_id == ARTICLE_CONTENT_TYPE_ID,
                Comment.object_id == obj.id,
            )
            .all()
        )
    return {
        'id': obj.id,
        'categories': [category.id for category in obj.categories],
        'title': obj.title,
        'title_h1': obj.title_h1,
        'description': obj.description,
        'content': obj.content,
        'image': obj.image or None,
        'read_count': obj.read_count,
        'image_url': obj.image_url,
        'slug': obj.slug,
        'user': _fk(obj.user_id),
        'username': obj.user.username if obj.user is not None else None,
        'is_active': obj.is_active,
        'is_approval': obj.is_approval,
        'approval_user': _fk(obj.approval_user_id),
        'is_delete': obj.is_delete,
        'comments': [serialize_comment(comment, session) for comment in comments],
        'created_at': isoformat(obj.created_at),
        'updated_at': isoformat(obj.updated_at),
    }


def serialize_article_list(obj: Any) -> Dict[str, Any]:
    return {
        'id': obj.id,
        'title': obj.title,
        'title_h1': obj.title_h1,
        'description': obj.description,
        'image': obj.image or None,
        'read_count': obj.read_count,
        'image_url': obj.image_url,
        'slug': obj.slug,
        'categories': [category.id for category in obj.categories],
        'user': _fk(obj.user_id),
        'username': obj.user.username if obj.user is not None else None,
        'is_active': obj.is_active,
        'is_approval': obj.is_approval,
        'created_at': isoformat(obj.created_at),
        'updated_at': isoformat(obj.updated_at),
    }


# ---------------------------------------------------------------------------
# Slider
# ---------------------------------------------------------------------------

class SliderInput(BaseModel):
    model_config = ConfigDict(extra='ignore')
    nullable_fields: ClassVar[FrozenSet[str]] = frozenset({
        'description', 'link', 'image', 'approval_user',
    })

    title: str = Field(min_length=1)
    description: Optional[str] = None
    link: Optional[str] = None
    image: Optional[str] = None
    is_approval: Optional[bool] = None
    approval_user: Optional[int] = None


SLIDER_INPUT_ORDER = ('title', 'description', 'link', 'image', 'is_approval', 'approval_user')


def serialize_slider(obj: Any) -> Dict[str, Any]:
    return {
        'id': obj.id,
        'title': obj.title,
        'description': obj.description,
        'link': obj.link,
        'image': obj.image or None,
        'image_url': obj.image_url,
        'user': _fk(obj.user_id),
        'username': obj.user.username if obj.user is not None else None,
        'is_active': obj.is_active,
        'is_approval': obj.is_approval,
        'approval_user': _fk(obj.approval_user_id),
        'is_delete': obj.is_delete,
        'created_at': isoformat(obj.created_at),
        'updated_at': isoformat(obj.updated_at),
    }


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------

class MessageInput(BaseModel):
    model_config = ConfigDict(extra='ignore')
    nullable_fields: ClassVar[FrozenSet[str]] = frozenset({'sender', 'user'})

    sender: Optional[int] = None
    user: Optional[int] = None
    subject: str = Field(min_length=1)
    content: str = Field(min_length=1)
    ip: Optional[str] = None
    is_read: Optional[bool] = None
    is_delete: Optional[bool] = None


MESSAGE_INPUT_ORDER = ('sender', 'user', 'subject', 'content', 'ip', 'is_read', 'is_delete')


def serialize_message(obj: Any) -> Dict[str, Any]:
    return {
        'id': obj.id,
        'created_at': isoformat(obj.created_at),
        'sender': _fk(obj.sender_id),
        'user': _fk(obj.user_id),
        'subject': obj.subject,
        'content': obj.content,
        'ip': obj.ip,
        'is_read': obj.is_read,
        'is_delete': obj.is_delete,
    }
