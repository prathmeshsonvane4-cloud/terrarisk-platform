from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, verify_password
from app.database.session import get_db
from app.models.user import AppUser
from app.schemas.auth import LoginRequest, LoginResponse

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> LoginResponse:
    result = await db.execute(select(AppUser).where(AppUser.email == payload.email))
    user = result.scalar_one_or_none()

    # Same generic failure for "no such user" and "wrong password" — never
    # confirm whether an email exists (Blueprint §03 business rule).
    invalid_credentials = HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    if user is None or not user.is_active:
        raise invalid_credentials
    if not verify_password(payload.password, user.password_hash):
        raise invalid_credentials

    token, expires_in = create_access_token(user_id=user.id, role=user.role.value)
    return LoginResponse(access_token=token, role=user.role, expires_in=expires_in)
