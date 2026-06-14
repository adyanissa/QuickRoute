from pydantic import BaseModel, Field


class GenerateInvitationCodeResponse(BaseModel):
    code: str
    is_used: bool
    message: str


class ValidateInvitationCodeRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=30)


class ValidateInvitationCodeResponse(BaseModel):
    valid: bool
    message: str