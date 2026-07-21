from typing import Literal

from pydantic import BaseModel, EmailStr, Field


UserRole = Literal[
    "super_admin",
    "global_manager",
    "building_manager",
    "regular_user",
]


class RegisterRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=72)


class SignupRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=72)
    code: str = Field(..., min_length=6, max_length=30)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=72)


class UserResponse(BaseModel):
    id: str
    full_name: str
    email: EmailStr
    role: UserRole
    building_ids: list[str]
    all_buildings: bool


class AuthResponse(BaseModel):
    success: bool
    message: str
    user: UserResponse

    # Present on signup/register/login so the frontend can attach the
    # token to subsequent admin requests without a second round trip.
    access_token: str
    token_type: str = "bearer"
    expires_at: str