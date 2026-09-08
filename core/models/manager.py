"""A very small query helper shared by the declarative models.

This is deliberately *not* a general object-relational mapper: SQLAlchemy is
the mapper.  It is a thin repository facade over ``Session`` + ``select()``
so that call sites read the same way they did before the port and so that
"row not found" keeps raising a per-model exception rather than returning
``None``.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional

from sqlalchemy import func, select

from app import db


class ObjectDoesNotExist(Exception):
    """Raised when a lookup matches no row."""


class MultipleObjectsReturned(Exception):
    """Raised when a ``get`` lookup matches more than one row."""


class QuerySet:
    """Lazily evaluated wrapper around a SQLAlchemy ``Select``."""

    def __init__(self, model, statement=None, session=None):
        self.model = model
        self.session = session or db.get_session()
        self.statement = select(model) if statement is None else statement

    def _clone(self, statement) -> 'QuerySet':
        return QuerySet(self.model, statement, self.session)

    def filter(self, *criteria, **lookups) -> 'QuerySet':
        statement = self.statement
        if criteria:
            statement = statement.where(*criteria)
        for column, value in _resolve(self.model, lookups):
            statement = statement.where(column == value)
        return self._clone(statement)

    def exclude(self, **lookups) -> 'QuerySet':
        statement = self.statement
        for column, value in _resolve(self.model, lookups):
            statement = statement.where(column != value)
        return self._clone(statement)

    def order_by(self, *columns) -> 'QuerySet':
        return self._clone(self.statement.order_by(*columns))

    def limit(self, value: int) -> 'QuerySet':
        return self._clone(self.statement.limit(value))

    def offset(self, value: int) -> 'QuerySet':
        return self._clone(self.statement.offset(value))

    def distinct(self) -> 'QuerySet':
        return self._clone(self.statement.distinct())

    def all(self) -> List[Any]:
        return list(self.session.scalars(self.statement).unique())

    def first(self) -> Optional[Any]:
        rows = self.limit(1).all()
        return rows[0] if rows else None

    def get(self, *criteria, **lookups) -> Any:
        rows = self.filter(*criteria, **lookups).all()
        if not rows:
            raise self.model.DoesNotExist(
                '%s matching query does not exist.' % self.model.__name__)
        if len(rows) > 1:
            raise self.model.MultipleObjectsReturned(
                'get() returned more than one %s.' % self.model.__name__)
        return rows[0]

    def count(self) -> int:
        subquery = self.statement.order_by(None).subquery()
        return int(self.session.scalar(
            select(func.count()).select_from(subquery)) or 0)

    def exists(self) -> bool:
        return self.first() is not None

    def delete(self) -> int:
        rows = self.all()
        for row in rows:
            self.session.delete(row)
        self.session.flush()
        return len(rows)

    def __iter__(self) -> Iterator[Any]:
        return iter(self.all())

    def __len__(self) -> int:
        return len(self.all())

    def __getitem__(self, item):
        return self.all()[item]

    def __bool__(self) -> bool:
        return self.exists()


def _resolve(model, lookups: Dict[str, Any]):
    """Turn ``field=value`` / ``field_id=value`` pairs into column pairs."""
    for key, value in lookups.items():
        column = getattr(model, key, None)
        if column is None:
            raise AttributeError(
                '%s has no field %r' % (model.__name__, key))
        yield column, value


class Manager:
    """Descriptor exposing :class:`QuerySet` as ``Model.objects``."""

    def __init__(self):
        self.model = None

    @property
    def session(self):
        return db.get_session()

    def __set_name__(self, owner, name):
        self.model = owner

    def __get__(self, instance, owner=None):
        manager = self.__class__()
        manager.model = owner or self.model
        return manager

    def get_queryset(self) -> QuerySet:
        return QuerySet(self.model)

    def create(self, **fields) -> Any:
        session = db.get_session()
        instance = self.model(**fields)
        save = getattr(instance, 'save', None)
        if callable(save):
            save(session=session)
        else:
            session.add(instance)
            session.flush()
        return instance

    def filter(self, *criteria, **lookups) -> QuerySet:
        return self.get_queryset().filter(*criteria, **lookups)

    def exclude(self, **lookups) -> QuerySet:
        return self.get_queryset().exclude(**lookups)

    def get(self, *criteria, **lookups) -> Any:
        return self.get_queryset().get(*criteria, **lookups)

    def all(self) -> QuerySet:
        return self.get_queryset()

    def count(self) -> int:
        return self.get_queryset().count()

    def order_by(self, *columns) -> QuerySet:
        return self.get_queryset().order_by(*columns)
