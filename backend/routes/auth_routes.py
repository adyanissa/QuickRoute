from fastapi import APIRouter, Depends

from core.auth_deps import get_current_user
from logic.auth_logic import register_user, signup_user, login_user
from models.user_model import User
from schemas.auth_schema import (
    RegisterRequest,
    SignupRequest,
    LoginRequest,
    AuthResponse,
    UserResponse,
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


@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(get_current_user)):
    return UserResponse(
        id=str(user.id),
        full_name=user.full_name,
        email=user.email,
        role=user.role,
        building_ids=user.building_ids,
        all_buildings=user.all_buildings,
    )