from pydantic import BaseModel, EmailStr

from app.models.enums import UserRole


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: UserRole
    expires_in: int
    # M2A: the app shell displays the officer's name — nothing in the JWT
    # payload itself carries it (sub/role/exp/iat only, by design, to keep
    # the token small), so the login response is the one place to hand it
    # to the frontend without a second round-trip.
    full_name: str
