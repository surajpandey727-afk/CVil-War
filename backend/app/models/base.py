"""SQLAlchemy declarative base and shared mixins."""

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column


def generate_uuid() -> str:
    """Generate a UUID4 string for primary keys."""
    return uuid.uuid4().hex


def pg_enum(py_enum: type[Enum], name: str) -> SAEnum:
    """A native ENUM on PostgreSQL, VARCHAR+CHECK on SQLite.

    ``values_callable`` is non-negotiable: it persists the lowercase enum *values*
    (e.g. ``"queued"``) rather than the uppercase member *names* SQLAlchemy uses by
    default — the lowercase values are what the entire codebase compares against.
    """
    return SAEnum(
        py_enum,
        name=name,
        native_enum=True,
        values_callable=lambda enum: [member.value for member in enum],
        validate_strings=True,
    )


class TenantMixin:
    """Adds a ``user_id`` FK that scopes a row to its owning user.

    Combined with the ``do_orm_execute`` filter in :mod:`app.db.tenant`, every ORM
    SELECT touching a ``TenantMixin`` entity is automatically scoped to the current
    user. INSERTs must still set ``user_id`` explicitly (the filter is SELECT-only).
    """

    @declared_attr
    def user_id(cls) -> Mapped[str]:  # noqa: N805
        return mapped_column(
            String(32),
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


class TimestampMixin:
    """Mixin that adds created_at and updated_at timestamp columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class UUIDPrimaryKeyMixin:
    """Mixin that adds a UUID primary key column."""

    id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=generate_uuid,
    )
