from fastapi import APIRouter

from logic.invitation_code_logic import (
    generate_invitation_code,
    validate_invitation_code
)
from schemas.invitation_code_schema import (
    GenerateInvitationCodeResponse,
    ValidateInvitationCodeRequest,
    ValidateInvitationCodeResponse
)


router = APIRouter(
    prefix="/api/invitation-codes",
    tags=["Invitation Codes"]
)


@router.post("/generate", response_model=GenerateInvitationCodeResponse)
async def generate_code():
    return await generate_invitation_code()


@router.post("/validate", response_model=ValidateInvitationCodeResponse)
async def validate_code(request: ValidateInvitationCodeRequest):
    return await validate_invitation_code(request.code)