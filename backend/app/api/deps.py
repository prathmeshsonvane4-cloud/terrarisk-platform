from collections.abc import Awaitable, Callable
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from app.core.security import decode_access_token
from app.database.session import get_db
from app.models.enums import UserRole
from app.models.user import AppUser

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> AppUser:
    """Resolve the caller's AppUser from a bearer JWT.

    Every endpoint that isn't /auth/login depends on this — there is no
    unauthenticated path through the API (Blueprint §03/§07 CTO review:
    a bank will not pilot software with no access control).
    """
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    user_id = UUID(payload["sub"])
    result = await db.execute(select(AppUser).where(AppUser.id == user_id, AppUser.is_active.is_(True)))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    return user


def require_role(*allowed_roles: UserRole) -> Callable[[AppUser], Awaitable[AppUser]]:
    """Role-scoping dependency factory — enforced server-side, never just
    hidden in the UI (Blueprint §03 business rule)."""

    async def _check(user: AppUser = Depends(get_current_user)) -> AppUser:
        if user.role not in allowed_roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Insufficient role for this operation")
        return user

    return _check


async def user_can_access_owned_resource(db: AsyncSession, current_user: AppUser, owner_id: UUID) -> bool:
    """Shared owner-or-same-branch authorization check, used by every
    endpoint that scopes a resource to whoever created/drew it (jobs,
    reports — see app/api/jobs.py and app/api/reports.py). Consolidated
    here after a Staff Engineer review found the same check duplicated in
    both places with only the resource type differing.

    Callers should treat a False result as a 404, not a 403 — a resource
    that exists but belongs to someone else must be indistinguishable from
    one that doesn't exist at all, to avoid leaking valid resource ids to
    an unauthorized caller.
    """
    if current_user.id == owner_id:
        return True
    if current_user.branch_id is None:
        return False
    owner = await db.get(AppUser, owner_id)
    return owner is not None and owner.branch_id == current_user.branch_id


def owned_or_branch_filter(current_user: AppUser, owner: type[AppUser]) -> ColumnElement[bool]:
    """SQL-expression twin of `user_can_access_owned_resource`, for list
    endpoints that must scope a query rather than check one already-loaded
    row (M2B P7 workspace lists — Product Design v2 §5 "branch-scoped
    visibility"). `owner` is an AppUser aliased onto the resource's owner
    column by the caller's join. Same rule, same effect: a resource outside
    the caller's own-or-branch scope is simply absent from the result set,
    never revealed via a total count or an error message.

    `current_user` is an already-loaded ORM instance (not a column/alias),
    so `current_user.branch_id` is a concrete Python value here, never a
    SQL expression — the branchless case is resolved in Python, not pushed
    into the query, and only a real branch id ever becomes a SQL clause.
    """
    if current_user.branch_id is None:
        return owner.id == current_user.id
    return or_(owner.id == current_user.id, owner.branch_id == current_user.branch_id)
