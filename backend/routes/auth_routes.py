from fastapi import APIRouter

from logic.auth_logic import register_user, signup_user, login_user
from schemas.auth_schema import (
    RegisterRequest,
    SignupRequest,
    LoginRequest,
    AuthResponse
)


router = APIRouter(
    prefix="/api/auth",
    tags=["Auth"]
)


@router.post("/register", response_model=AuthResponse)
async def register(request: RegisterRequest):
    return await register_user(request)


@router.post("/signup", response_model=AuthResponse)
async def signup(request: SignupRequest):
    return await signup_user(request)


@router.post("/login", response_model=AuthResponse)
async def login(request: LoginRequest):
    return await login_user(request)