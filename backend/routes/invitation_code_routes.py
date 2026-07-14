from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from logic.invitation_code_logic import (
    generate_invitation_code,
    validate_invitation_code
)
from models.invitation_code_model import InvitationCode
from schemas.invitation_code_schema import (
    GenerateInvitationCodeResponse,
    ValidateInvitationCodeRequest,
    ValidateInvitationCodeResponse
)


router = APIRouter(
    prefix="/api/invitation-codes",
    tags=["Invitation Codes"]
)


InvitationRole = Literal[
    "super_admin",
    "global_manager",
    "building_manager",
    "regular_user",
]


class DevCreateInvitationCodeRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=30)
    role: InvitationRole = "regular_user"
    building_ids: list[str] = Field(default_factory=list)
    all_buildings: bool = False


@router.post("/generate", response_model=GenerateInvitationCodeResponse)
async def generate_code():
    return await generate_invitation_code()


@router.post("/validate", response_model=ValidateInvitationCodeResponse)
async def validate_code(request: ValidateInvitationCodeRequest):
    return await validate_invitation_code(request.code)


@router.post("/dev-create")
async def dev_create_invitation_code(request: DevCreateInvitationCodeRequest):
    existing_code = await InvitationCode.find_one(
        InvitationCode.code == request.code
    )

    if existing_code is not None:
        return {
            "success": True,
            "message": "Invitation code already exists",
            "invitation_code": {
                "code": existing_code.code,
                "role": existing_code.role,
                "building_ids": existing_code.building_ids,
                "all_buildings": existing_code.all_buildings,
                "is_used": existing_code.is_used,
                "used_by_email": existing_code.used_by_email
            }
        }

    new_code = InvitationCode(
        code=request.code,
        role=request.role,
        building_ids=request.building_ids,
        all_buildings=request.all_buildings,
        is_used=False
    )

    await new_code.insert()

    return {
        "success": True,
        "message": "Invitation code created successfully",
        "invitation_code": {
            "code": new_code.code,
            "role": new_code.role,
            "building_ids": new_code.building_ids,
            "all_buildings": new_code.all_buildings,
            "is_used": new_code.is_used,
            "used_by_email": new_code.used_by_email
        }
    }