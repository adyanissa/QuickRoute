import secrets
import string

from fastapi import HTTPException

from core.errors import INVALID_INVITATION_CODE, INVITATION_CODE_ALREADY_USED
from models.invitation_code_model import InvitationCode


def generate_random_code(length: int = 8) -> str:
    characters = string.ascii_uppercase + string.digits
    random_part = "".join(secrets.choice(characters) for _ in range(length))
    return f"QR-{random_part}"


async def generate_invitation_code():
    code = generate_random_code()

    while await InvitationCode.find_one(InvitationCode.code == code):
        code = generate_random_code()

    invitation_code = InvitationCode(code=code)

    await invitation_code.insert()

    return {
        "code": invitation_code.code,
        "is_used": invitation_code.is_used,
        "message": "Invitation code generated successfully"
    }


async def validate_invitation_code(code: str):
    invitation_code = await InvitationCode.find_one(InvitationCode.code == code)

    if invitation_code is None:
        raise HTTPException(**INVALID_INVITATION_CODE)

    if invitation_code.is_used:
        raise HTTPException(**INVITATION_CODE_ALREADY_USED)

    return {
        "valid": True,
        "message": "Invitation code is valid"
    }