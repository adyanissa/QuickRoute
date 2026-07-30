from beanie import PydanticObjectId
from fastapi import HTTPException

from core.errors import EMAIL_ALREADY_EXISTS, INVALID_CREDENTIALS
from core.security import create_access_token, hash_password, verify_password
from logic.invitation_code_logic import (
    InvitationCodeConsumptionError,
    find_and_validate_code_for_signup,
    release_invitation_code_reservation,
    reserve_invitation_code_for_signup,
)
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
    # Step 1: validate code — exists, active, unused, not expired, not
    # revoked, and (if restricted) the intended email matches. This is a
    # fast pre-check that gives precise error messages; it does not
    # reserve anything yet, so it is safe to run before the account-field
    # validation FastAPI already performed via the SignupRequest schema.
    try:
        invitation_code = await find_and_validate_code_for_signup(
            request.code, request.email
        )
    except InvitationCodeConsumptionError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail)

    existing_user = await User.find_one(User.email == request.email)

    if existing_user is not None:
        raise HTTPException(**EMAIL_ALREADY_EXISTS)

    # Step 2: atomically reserve the code (single-use guarantee). Only one
    # of any number of concurrent requests racing on the same code can
    # succeed here — the update is a single conditional update_one at the
    # driver level, guarded on is_used == False. Reserved *before* the
    # user is created (with the user's id pre-assigned) so the window
    # where a code could be "double spent" between check and use is
    # closed entirely, rather than merely narrowed.
    new_user_id = PydanticObjectId()

    reserved = await reserve_invitation_code_for_signup(
        invitation_code.id, str(new_user_id), request.email
    )

    if not reserved:
        # Another request consumed this exact code in the tiny window
        # between our pre-check and this atomic reservation.
        raise HTTPException(
            status_code=400, detail="Invitation code already used"
        )

    # Step 3: create the user with role/building scope copied verbatim
    # from the (now-reserved) invitation code — never from client input.
    try:
        new_user = User(
            id=new_user_id,
            full_name=request.full_name,
            email=request.email,
            password=hash_password(request.password),
            role=invitation_code.role,
            building_ids=list(invitation_code.building_ids),
            all_buildings=invitation_code.all_buildings,
        )
        await new_user.insert()
    except Exception:
        # Compensating rollback: user creation failed after the code was
        # already marked used — release the reservation so the code is
        # not incorrectly burned.
        await release_invitation_code_reservation(invitation_code.id)
        raise

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