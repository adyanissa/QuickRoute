from datetime import datetime, timezone

from fastapi import HTTPException

from core.errors import (
    EMAIL_ALREADY_EXISTS,
    INVALID_CREDENTIALS,
    INVALID_INVITATION_CODE,
    INVITATION_CODE_ALREADY_USED
)
from core.security import create_access_token, hash_password, verify_password
from models.invitation_code_model import InvitationCode
from models.user_model import User
from schemas.auth_schema import RegisterRequest, SignupRequest, LoginRequest


async def register_user(request: RegisterRequest):
    existing_user = await User.find_one(User.email == request.email)

    if existing_user is not None:
        raise HTTPException(**EMAIL_ALREADY_EXISTS)

    new_user = User(
        full_name=request.full_name,
        email=request.email,
        password=hash_password(request.password),
        role="regular_user",
        building_ids=[],
        all_buildings=False
    )

    await new_user.insert()

    token, expires_at = create_access_token(
        user_id=str(new_user.id),
        email=new_user.email,
        role=new_user.role,
    )

    return {
        "success": True,
        "message": "User registered successfully",
        "user": {
            "id": str(new_user.id),
            "full_name": new_user.full_name,
            "email": new_user.email,
            "role": new_user.role,
            "building_ids": new_user.building_ids,
            "all_buildings": new_user.all_buildings
        },
        "access_token": token,
        "token_type": "bearer",
        "expires_at": expires_at.isoformat(),
    }


async def signup_user(request: SignupRequest):
    invitation_code = await InvitationCode.find_one(
        InvitationCode.code == request.code
    )

    if invitation_code is None:
        raise HTTPException(**INVALID_INVITATION_CODE)

    if invitation_code.is_used:
        raise HTTPException(**INVITATION_CODE_ALREADY_USED)

    existing_user = await User.find_one(User.email == request.email)

    if existing_user is not None:
        raise HTTPException(**EMAIL_ALREADY_EXISTS)

    new_user = User(
        full_name=request.full_name,
        email=request.email,
        password=hash_password(request.password),

        # Permissions are copied from the invitation code
        role=invitation_code.role,
        building_ids=list(invitation_code.building_ids),
        all_buildings=invitation_code.all_buildings
    )

    await new_user.insert()

    invitation_code.is_used = True
    invitation_code.used_by_email = request.email
    invitation_code.used_at = datetime.now(timezone.utc)

    await invitation_code.save()

    token, expires_at = create_access_token(
        user_id=str(new_user.id),
        email=new_user.email,
        role=new_user.role,
    )

    return {
        "success": True,
        "message": "User signed up successfully",
        "user": {
            "id": str(new_user.id),
            "full_name": new_user.full_name,
            "email": new_user.email,
            "role": new_user.role,
            "building_ids": new_user.building_ids,
            "all_buildings": new_user.all_buildings
        },
        "access_token": token,
        "token_type": "bearer",
        "expires_at": expires_at.isoformat(),
    }


async def login_user(request: LoginRequest):
    user = await User.find_one(User.email == request.email)

    if user is None or not verify_password(request.password, user.password):
        raise HTTPException(**INVALID_CREDENTIALS)

    token, expires_at = create_access_token(
        user_id=str(user.id),
        email=user.email,
        role=user.role,
    )

    return {
        "success": True,
        "message": "Login successful",
        "user": {
            "id": str(user.id),
            "full_name": user.full_name,
            "email": user.email,
            "role": user.role,
            "building_ids": user.building_ids,
            "all_buildings": user.all_buildings
        },
        "access_token": token,
        "token_type": "bearer",
        "expires_at": expires_at.isoformat(),
    }