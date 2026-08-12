"""Shared FastAPI dependencies for route injection."""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthError, AuthorizationError
from app.core.security import decode_token
from app.db.redis import get_redis as _get_redis
from app.db.session import async_session_factory
from app.db.session import get_db as _get_db
from app.db.tenant import current_user_id
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=True)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Unscoped database session dependency (no tenant filter)."""
    async for session in _get_db():
        yield session


def get_redis() -> Redis | None:
    """Redis client dependency. Returns None if Redis unavailable."""
    return _get_redis()


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Resolve the authenticated, active, non-deleted user from a bearer token."""
    payload = decode_token(token, expected_type="access")
    sub = payload.get("sub")
    if not isinstance(sub, str):
        raise AuthError("Invalid token subject")
    user = await db.get(User, sub)
    if user is None or not user.is_active or user.deleted_at is not None:
        raise AuthError("Invalid or inactive user")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_superuser(user: CurrentUser) -> User:
    """Authorize a superuser-only route (admin/health views)."""
    if not user.is_superuser:
        raise AuthorizationError("Superuser privileges required")
    return user


SuperUser = Annotated[User, Depends(require_superuser)]


async def get_tenant_db(user: CurrentUser) -> AsyncGenerator[AsyncSession, None]:
    """Yield a session whose ORM SELECTs are auto-scoped to the current user.

    Sets the ``current_user_id`` ContextVar for the request lifetime; the
    ``do_orm_execute`` filter in :mod:`app.db.tenant` does the rest.
    """
    token = current_user_id.set(user.id)
    try:
        async with async_session_factory() as session:
            yield session
    finally:
        current_user_id.reset(token)


TenantDB = Annotated[AsyncSession, Depends(get_tenant_db)]
