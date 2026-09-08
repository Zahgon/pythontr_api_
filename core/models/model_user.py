"""The project user model and its manager."""
from __future__ import annotations

import datetime as _datetime
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app import settings
from app.db import BIG_PK, Base
from app.security import check_password as _check_password
from app.security import make_password
from app.text import slugify
from core.models.manager import Manager, MultipleObjectsReturned, ObjectDoesNotExist
from core.models.model_support import (
    Group,
    Permission,
    core_user_groups,
    core_user_user_permissions,
    utcnow,
)


def avatar_image_file_path(instance, filename):
    f_name, ext = filename.split('.')
    allowed_chars = \
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._"
    sanitized_filename = ''.join(c for c in f_name if c in allowed_chars)
    slug = slugify(sanitized_filename)
    file_path = f'{settings.AVATAR_ROOT}{instance.pk}/{slug}.{ext}'
    return file_path


class UserManager(Manager):
    """Creates users, hashing the password on the way in."""

    def create_user(self, email, password=None, **extra_fields):
        session = extra_fields.pop('session', None) or self.session
        for key, value in (('email', email),):
            if not value:
                raise ValueError('Users must have an {} address'.format(value))

        user = self.model(email=self.normalize_email(email), **extra_fields)
        user.set_password(password)
        user.save(session=session)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        session = extra_fields.pop('session', None) or self.session
        user = self.create_user(
            email, password, session=session, **extra_fields)
        user.is_active = True
        user.is_staff = True
        user.is_superuser = True
        user.save(session=session)
        return user

    @staticmethod
    def normalize_email(email):
        email = email or ''
        try:
            email_name, domain_part = email.strip().rsplit('@', 1)
        except ValueError:
            pass
        else:
            email = email_name + '@' + domain_part.lower()
        return email


class User(Base):
    """Application user. Authenticates with the e-mail address."""

    __tablename__ = 'core_user'

    DoesNotExist = type('DoesNotExist', (ObjectDoesNotExist,), {})
    MultipleObjectsReturned = type('MultipleObjectsReturned', (MultipleObjectsReturned,), {})

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS: List[str] = []

    objects = UserManager()

    id: Mapped[int] = mapped_column(BIG_PK, primary_key=True, autoincrement=True)
    password: Mapped[str] = mapped_column(String(128), nullable=False, default='')
    last_login: Mapped[Optional[_datetime.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_superuser: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    username: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, default='')
    name: Mapped[str] = mapped_column(String(255), nullable=False, default='')
    surname: Mapped[str] = mapped_column(String(255), nullable=False, default='')
    image: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    about_me: Mapped[str] = mapped_column(Text, nullable=False, default='')
    linkedin: Mapped[str] = mapped_column(String(255), nullable=False, default='')
    github: Mapped[str] = mapped_column(String(255), nullable=False, default='')
    is_notification_email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_staff: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_ban: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_delete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    slug: Mapped[str] = mapped_column(String(150), nullable=False, unique=True, default='')
    created_at: Mapped[_datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[_datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    groups: Mapped[List[Group]] = relationship(Group, secondary=core_user_groups, lazy='selectin')
    user_permissions: Mapped[List[Permission]] = relationship(
        Permission, secondary=core_user_user_permissions, lazy='selectin'
    )
    auth_token = relationship(
        'Token', back_populates='user', uselist=False, lazy='selectin', cascade='all, delete-orphan'
    )

    # -- authentication surface -------------------------------------------------
    @property
    def pk(self):
        return self.id

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def is_anonymous(self) -> bool:
        return False

    def set_password(self, raw_password):
        self.password = make_password(raw_password)

    def check_password(self, raw_password) -> bool:
        return _check_password(raw_password, self.password)

    def get_username(self):
        return getattr(self, self.USERNAME_FIELD)

    def has_perm(self, perm, obj=None) -> bool:
        return bool(self.is_active and self.is_superuser)

    def has_module_perms(self, app_label) -> bool:
        return bool(self.is_active and self.is_superuser)

    # -- project behaviour ------------------------------------------------------
    def get_slug(self, session=None):
        """Slugify the username, appending ``-N`` until the slug is free.

        The lookup does not exclude the row being saved, so re-saving an
        existing user walks its slug forward. That behaviour is relied upon by
        the suite and is reproduced here.
        """
        from app import db as _db

        session = session or _db.get_session()
        slug = slugify(str(self.username).replace('ı', 'i'))
        base_slug = slug
        counter = 1
        while session.query(User).filter(User.slug == slug).first() is not None:
            slug = '{}-{}'.format(base_slug, counter)
            counter += 1
        return slug

    def save(self, session=None):
        from app import db as _db

        session = session or _db.get_session()
        if not self.username:
            self.username = self.email.split('@')[0]
        if self.created_at is None:
            self.created_at = utcnow()
        self.updated_at = utcnow()
        self.slug = self.get_slug(session=session)
        session.add(self)
        session.flush()
        return self

    @property
    def image_url(self):
        if self.image:
            return str(self.image).replace(settings.APLICATION_NAME, '')
        return None

    def __str__(self) -> str:
        return self.email

    def __repr__(self) -> str:
        return '<User %s>' % (self.email,)


class AnonymousUser:
    """Stand-in used when a request carries no credentials."""

    id = None
    pk = None
    username = ''
    email = ''
    is_staff = False
    is_active = False
    is_superuser = False
    is_ban = False
    is_delete = False

    @property
    def is_authenticated(self) -> bool:
        return False

    @property
    def is_anonymous(self) -> bool:
        return True

    def check_password(self, raw_password) -> bool:
        return False

    def has_perm(self, perm, obj=None) -> bool:
        return False

    def has_module_perms(self, app_label) -> bool:
        return False

    def __str__(self) -> str:
        return 'AnonymousUser'

    def __eq__(self, other) -> bool:
        return isinstance(other, AnonymousUser)

    def __hash__(self) -> int:
        return hash('AnonymousUser')

    def __bool__(self) -> bool:
        return False
