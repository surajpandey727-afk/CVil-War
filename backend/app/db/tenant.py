"""Per-user tenant isolation — the "cannot be forgotten" SELECT filter.

A request sets :data:`current_user_id` (via the ``get_tenant_db`` dependency); a
``do_orm_execute`` event then injects ``WHERE user_id = :uid`` into every ORM SELECT
touching a :class:`~app.models.base.TenantMixin` entity — including lazy/relationship
loads. The default for any ORM SELECT is therefore "scoped": forgetting a manual
``.where(user_id=...)`` is safe; you must *opt out* with
``execution_options(skip_tenant_filter=True)``.

Caveats (each covered by a regression test):
  * SELECT-only. INSERTs must set ``user_id`` explicitly in the ``create_*`` services.
  * Bulk UPDATE/DELETE must add an explicit ``.where(Model.user_id == uid)``.
  * The worker / system paths must call ``current_user_id.set(...)`` before DB access;
    an unset contextvar means *no* implicit scope (fail-closed at the route layer).

Importing this module registers the event listener as a side effect; it must be
imported at application startup (done in ``app.main``).
"""

import contextvars

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import ORMExecuteState, with_loader_criteria

from app.models.base import TenantMixin

current_user_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_user_id", default=None
)


@event.listens_for(AsyncSession.sync_session_class, "do_orm_execute")
def _apply_tenant_filter(state: ORMExecuteState) -> None:
    """Scope every ORM SELECT on a TenantMixin entity to the current user."""
    uid = current_user_id.get()
    if uid is None:
        return
    if (
        state.is_select
        and not state.is_column_load
        and not state.is_relationship_load
        and not state.execution_options.get("skip_tenant_filter", False)
    ):
        state.statement = state.statement.options(
            with_loader_criteria(
                TenantMixin,
                lambda cls: cls.user_id == uid,
                include_aliases=True,
            )
        )
