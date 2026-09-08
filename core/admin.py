"""Model registry consumed by :mod:`app.admin_site`.

The baseline registered each model with an admin class that carried the
column list, filters, search fields and ordering.  Here the same
information is a plain data structure: ``app.admin_site`` reads it to
render the index, the changelist and the change form.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple, Type

from core.models import (
    Article,
    Category,
    Comment,
    Message,
    PageVisit,
    Slider,
    User,
)


class ModelAdmin:
    """Presentation metadata for one registered model."""

    def __init__(
        self,
        model: Type[object],
        app_label: str,
        model_name: str,
        verbose_name: str,
        verbose_name_plural: str,
        list_display: Sequence[str],
        list_filter: Sequence[str] = (),
        search_fields: Sequence[str] = (),
        ordering: Sequence[str] = ('-id',),
        readonly_fields: Sequence[str] = (),
        editable_fields: Sequence[str] = (),
        can_add: bool = True,
    ) -> None:
        self.model = model
        self.app_label = app_label
        self.model_name = model_name
        self.verbose_name = verbose_name
        self.verbose_name_plural = verbose_name_plural
        self.list_display = tuple(list_display)
        self.list_filter = tuple(list_filter)
        self.search_fields = tuple(search_fields)
        self.ordering = tuple(ordering)
        self.readonly_fields = tuple(readonly_fields)
        self.editable_fields = tuple(editable_fields)
        self.can_add = can_add

    @property
    def slug(self) -> str:
        return '%s/%s' % (self.app_label, self.model_name)

    def has_add_permission(self) -> bool:
        return self.can_add


USER_ADMIN = ModelAdmin(
    model=User,
    app_label='core',
    model_name='user',
    verbose_name='Kullanıcı',
    verbose_name_plural='Kullanıcılar',
    list_display=('id', 'email', 'username', 'name', 'surname', 'is_active', 'is_staff'),
    list_filter=('is_active', 'is_staff', 'is_ban', 'is_delete'),
    search_fields=('email', 'username', 'name', 'surname'),
    ordering=('id',),
    readonly_fields=('last_login', 'created_at', 'updated_at', 'slug'),
    editable_fields=(
        'email', 'username', 'name', 'surname', 'about_me', 'linkedin', 'github',
        'is_notification_email', 'is_active', 'is_staff', 'is_ban', 'is_delete',
    ),
)

CATEGORY_ADMIN = ModelAdmin(
    model=Category,
    app_label='core',
    model_name='category',
    verbose_name='Kategori',
    verbose_name_plural='Kategoriler',
    list_display=('id', 'name', 'title', 'short_name', 'sort'),
    search_fields=('name', 'title', 'short_name'),
    ordering=('id',),
    readonly_fields=('slug', 'created_at', 'updated_at'),
    editable_fields=('name', 'title', 'title_h1', 'description', 'content', 'short_name', 'sort'),
)

ARTICLE_ADMIN = ModelAdmin(
    model=Article,
    app_label='core',
    model_name='article',
    verbose_name='Makale',
    verbose_name_plural='Makaleler',
    list_display=('id', 'title', 'read_count', 'is_active', 'is_approval', 'is_delete'),
    list_filter=('is_active', 'is_approval', 'is_delete'),
    search_fields=('title', 'title_h1', 'description'),
    ordering=('-id',),
    readonly_fields=('slug', 'read_count', 'created_at', 'updated_at'),
    editable_fields=('title', 'title_h1', 'description', 'content', 'is_active', 'is_approval', 'is_delete'),
)

COMMENT_ADMIN = ModelAdmin(
    model=Comment,
    app_label='core',
    model_name='comment',
    verbose_name='Yorum',
    verbose_name_plural='Yorumlar',
    list_display=('id', 'name', 'email', 'content_type_id', 'object_id', 'is_active'),
    list_filter=('is_active', 'is_delete'),
    search_fields=('name', 'email', 'content'),
    ordering=('-id',),
    readonly_fields=('created_at',),
    editable_fields=('content', 'email', 'name', 'ip', 'is_active', 'is_delete'),
)

MESSAGE_ADMIN = ModelAdmin(
    model=Message,
    app_label='core',
    model_name='message',
    verbose_name='Mesaj',
    verbose_name_plural='Mesajlar',
    list_display=('id', 'subject', 'is_read', 'is_delete'),
    list_filter=('is_read', 'is_delete'),
    search_fields=('subject', 'content'),
    ordering=('-id',),
    readonly_fields=('created_at',),
    editable_fields=('subject', 'content', 'ip', 'is_read', 'is_delete'),
)

SLIDER_ADMIN = ModelAdmin(
    model=Slider,
    app_label='core',
    model_name='slider',
    verbose_name='Slayt',
    verbose_name_plural='Slaytlar',
    list_display=('id', 'title', 'is_active', 'is_approval', 'is_delete'),
    list_filter=('is_active', 'is_approval', 'is_delete'),
    search_fields=('title', 'description'),
    ordering=('-id',),
    readonly_fields=('created_at', 'updated_at'),
    editable_fields=('title', 'description', 'link', 'is_active', 'is_approval', 'is_delete'),
)

PAGE_VISIT_ADMIN = ModelAdmin(
    model=PageVisit,
    app_label='core',
    model_name='pagevisit',
    verbose_name='Sayfa ziyareti',
    verbose_name_plural='Sayfa ziyaretleri',
    list_display=('id', 'path', 'device_type', 'browser', 'os', 'timestamp'),
    list_filter=('device_type', 'method'),
    search_fields=('path', 'referrer', 'browser'),
    ordering=('-timestamp',),
    readonly_fields=('timestamp',),
    editable_fields=('path', 'referrer', 'method', 'device_type', 'language'),
    # The baseline overrides has_add_permission to return False, so the
    # index and changelist must not offer an "add" link for this model.
    can_add=False,
)

REGISTRY: Tuple[ModelAdmin, ...] = (
    USER_ADMIN,
    CATEGORY_ADMIN,
    ARTICLE_ADMIN,
    COMMENT_ADMIN,
    MESSAGE_ADMIN,
    SLIDER_ADMIN,
    PAGE_VISIT_ADMIN,
)

APP_VERBOSE_NAMES: Dict[str, str] = {'core': 'Core'}


def registered_models() -> Tuple[ModelAdmin, ...]:
    return REGISTRY


def find(app_label: str, model_name: str) -> Optional[ModelAdmin]:
    for entry in REGISTRY:
        if entry.app_label == app_label and entry.model_name == model_name:
            return entry
    return None


def grouped() -> List[Tuple[str, str, List[ModelAdmin]]]:
    """Return ``(app_label, app_name, entries)`` for the index page."""
    order: List[str] = []
    buckets: Dict[str, List[ModelAdmin]] = {}
    for entry in REGISTRY:
        if entry.app_label not in buckets:
            buckets[entry.app_label] = []
            order.append(entry.app_label)
        buckets[entry.app_label].append(entry)
    return [
        (label, APP_VERBOSE_NAMES.get(label, label.title()), buckets[label])
        for label in order
    ]
