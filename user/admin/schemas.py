"""Pydantic input models and serializers for the staff-facing admin API.

Key order in every ``serialize_*`` return value is part of the published wire
contract, so these build plain dicts rather than relying on response models.
"""

from __future__ import annotations

from typing import Any, ClassVar, Dict, FrozenSet, Optional

from pydantic import BaseModel, ConfigDict

from recipe.schemas import isoformat


class UserActionInput(BaseModel):
    """The only writable fields on ``PATCH /users/{pk}/``."""

    model_config = ConfigDict(extra='ignore')
    nullable_fields: ClassVar[FrozenSet[str]] = frozenset()

    is_active: Optional[bool] = None
    is_staff: Optional[bool] = None
    is_ban: Optional[bool] = None
    is_delete: Optional[bool] = None


USER_ACTION_INPUT_ORDER = ('is_active', 'is_staff', 'is_ban', 'is_delete')


def serialize_admin_user_list(obj: Any) -> Dict[str, Any]:
    return {
        'id': obj.id,
        'username': obj.username,
        'email': obj.email,
        'name': obj.name,
        'surname': obj.surname,
        'image': obj.image or None,
        'is_active': obj.is_active,
        'is_staff': obj.is_staff,
        'is_ban': obj.is_ban,
        'is_delete': obj.is_delete,
        'created_at': isoformat(obj.created_at),
        'updated_at': isoformat(obj.updated_at),
    }


def serialize_admin_user_detail(obj: Any) -> Dict[str, Any]:
    return {
        'id': obj.id,
        'username': obj.username,
        'email': obj.email,
        'name': obj.name,
        'surname': obj.surname,
        'image': obj.image or None,
        'about_me': obj.about_me,
        'is_active': obj.is_active,
        'is_staff': obj.is_staff,
        'is_ban': obj.is_ban,
        'is_delete': obj.is_delete,
        'created_at': isoformat(obj.created_at),
        'updated_at': isoformat(obj.updated_at),
    }


def serialize_admin_user_action(obj: Any) -> Dict[str, Any]:
    return {
        'is_active': obj.is_active,
        'is_staff': obj.is_staff,
        'is_ban': obj.is_ban,
        'is_delete': obj.is_delete,
    }


PAGE_VISIT_FIELDS = (
    'id',
    'user',
    'path',
    'timestamp',
    'ip_address',
    'user_agent',
    'referrer',
    'method',
    'device_type',
    'language',
    'session_id',
    'extra_data',
)


def serialize_page_visit(obj: Any) -> Dict[str, Any]:
    """Serialize one page-visit row.

    ``session_id`` and ``extra_data`` are declared on the baseline serializer
    but are not columns on the model, so reading them raises. That is a
    preserved defect: a populated list answers 500 while an empty list still
    answers 200 because this function is never called.
    """
    payload: Dict[str, Any] = {}
    for field in PAGE_VISIT_FIELDS:
        if field == 'user':
            payload['user'] = obj.user_id
        elif field == 'timestamp':
            payload['timestamp'] = isoformat(obj.timestamp)
        elif field == 'ip_address':
            value = obj.ip_address
            payload['ip_address'] = str(value) if value is not None else None
        else:
            payload[field] = getattr(obj, field)
    return payload
