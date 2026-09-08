"""Object level permission predicates for the recipe routes.

The baseline expressed these as permission classes attached to a viewset.
Here they are plain callables consumed by :func:`app.deps.access` and by the
route bodies through :func:`app.deps.check_object_permission`.
"""
from __future__ import annotations

from typing import Any

from app.deps import SAFE_METHODS, Access


def is_authenticated_and_owner(ctx: Access, obj: Any) -> bool:
    """Owner check used by article, slider, comment and message routes.

    Safe methods always pass.  A row without a ``user`` column can never be
    owned, so it is refused rather than treated as public.
    """
    if ctx.request.method in SAFE_METHODS:
        return True
    if not ctx.is_authenticated:
        return False
    owner = getattr(obj, 'user', None)
    if owner is None:
        return False
    return getattr(owner, 'id', None) == ctx.user.id


def is_authenticated_and_owner_or_admin(ctx: Access, obj: Any) -> bool:
    """Owner-or-staff check used by ``DELETE /api/recipe/articles/<pk>/``."""
    if not ctx.is_authenticated:
        return False
    if ctx.is_staff:
        return True
    owner = getattr(obj, 'user', None)
    if owner is None:
        return False
    return getattr(owner, 'id', None) == ctx.user.id
