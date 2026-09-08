"""Reporting helper retained from the baseline.

Nothing imports this module; it stayed dead in the original tree and stays dead
here so the migration does not silently drop a public name.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict

from sqlalchemy import func, select

from app.db import get_session
from core.models.model_support import utcnow


def get_time_based_stats(model: Any) -> Dict[str, int]:
    """Count rows created today, this week and this month."""
    session = get_session()
    now = utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    def count_since(moment: Any) -> int:
        statement = select(func.count()).select_from(model).where(
            model.created_at >= moment
        )
        return int(session.execute(statement).scalar_one())

    return {
        'today': count_since(today),
        'this_week': count_since(today - timedelta(days=today.weekday())),
        'this_month': count_since(today.replace(day=1)),
    }
