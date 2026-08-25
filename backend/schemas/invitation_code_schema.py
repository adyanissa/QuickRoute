from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

from models.invitation_code_model import InvitationRole

InvitationCodeStatus = Literal["active", "used", "expired", "revoked"]


class InvitationCodeCreate(BaseModel):
    role: InvitationRole

    all_buildings: bool = False
    building_ids: list[str] = Field(default_factory=list)

    # Additive/optional (RBAC/dashboard cleanup task, Phase 2/4) — only
    # meaningful for building_manager invitations; validated in
    # logic/invitation_code_logic.validate_role_and_scope_for_creation.
    map_group_ids: list[str] = Field(default_factory=list)
    map_ids: list[str] = Field(default_factory=list)

    intended_email: Optional[EmailStr] = None

    # Absolute expiry timestamp chosen by the admin UI (it converts the
    # "24 hours / 7 days / 30 days / custom date" preset into a concrete
    # datetime before sending). None = no expiration.
    expires_at: Optional[datetime] = None

    # Optional custom code. When omitted, the server generates a secure
    # random one — the preferred/default path.
    code: Optional[str] = Field(default=None, min_length=6, max_length=30)

    @field_validator("code")
    @classmethod
    def _normalize_code(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip().upper()
        return normalized or None

    @field_validator("intended_email")
    @classmethod
    def _normalize_email(cls, value):
        if value is None:
            return None
        return str(value).strip().lower()

    @field_validator("building_ids", "map_group_ids", "map_ids")
    @classmethod
    def _dedupe_id_list(cls, value: list[str]) -> list[str]:
        seen = []
        for item_id in value or []:
            if item_id and item_id not in seen:
                seen.append(item_id)
        return seen


class InvitationCodeResponse(BaseModel):
    id: str
    code: str

    role: InvitationRole
    all_buildings: bool
    building_ids: list[str]
    map_group_ids: list[str] = Field(default_factory=list)
    map_ids: list[str] = Field(default_factory=list)

    intended_email: Optional[str] = None
    expires_at: Optional[datetime] = None

    status: InvitationCodeStatus
    is_active: bool
    is_used: bool

    created_by_user_id: Optional[str] = None
    created_by_name: Optional[str] = None
    created_at: datetime

    used_at: Optional[datetime] = None
    used_by_user_id: Optional[str] = None
    used_by_email: Optional[str] = None

    revoked_at: Optional[datetime] = None
    revoked_by_user_id: Optional[str] = None


class GenerateInvitationCodeResponse(BaseModel):
    code: str
    is_used: bool
    message: str


class ValidateInvitationCodeRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=30)


class ValidateInvitationCodeResponse(BaseModel):
    """
    Safe, pre-signup preview of an invitation code. Deliberately excludes
    anything about who created it or who used it — this endpoint is called
    by unauthenticated visitors on the Sign Up screen.
    """

    valid: bool
    message: str

    role: Optional[InvitationRole] = None
    all_buildings: Optional[bool] = None
    building_ids: list[str] = Field(default_factory=list)
    buildings: list[dict] = Field(default_factory=list)

    # RBAC/dashboard cleanup task, Phase 3: previously missing from this
    # public pre-signup preview response — added for consistency with
    # InvitationCodeCreate/InvitationCodeResponse, which have carried these
    # since Phase 2. Safe to expose here: these are just id lists, no more
    # sensitive than building_ids already returned by this same endpoint.
    map_group_ids: list[str] = Field(default_factory=list)
    map_ids: list[str] = Field(default_factory=list)

    intended_email: Optional[str] = None
    expires_at: Optional[datetime] = None
