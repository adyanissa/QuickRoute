"""
Users & Access request/response models.

The response model is an allow-list, not a projection of the User
document: `password` (the bcrypt hash) has no field here at all, so no
future edit to the model can accidentally start returning it.
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


AdminAssignableRole = Literal["super_admin", "global_manager", "building_manager"]


class AssignedBuildingSummary(BaseModel):
    """Human-readable identity of the building an account administers.
    Resolved server-side so the UI never has to render a raw ObjectId as a
    person's responsibility — and never has to fetch buildings it may not
    be allowed to see just to translate an id into a name."""

    id: str
    name: str
    site: Optional[str] = None


class AdminUserResponse(BaseModel):
    id: str
    full_name: str
    email: str
    role: str

    # Raw scope, kept for the edit form's own round-trip only. Never the
    # primary thing the UI displays as "responsibility".
    building_ids: list[str] = Field(default_factory=list)
    all_buildings: bool = False
    map_group_ids: list[str] = Field(default_factory=list)
    map_ids: list[str] = Field(default_factory=list)

    # Resolved, display-ready scope.
    assigned_building: Optional[AssignedBuildingSummary] = None
    scope_kind: str

    created_at: datetime

    # Whether the CALLER may act on this record, decided by the backend's
    # own hierarchy rules rather than re-derived in the browser. The UI
    # uses it to hide actions; the API re-checks on every mutation.
    can_edit: bool = False
    can_delete: bool = False


class AdminUserUpdate(BaseModel):
    """Only the three things this feature is allowed to change.

    Deliberately absent: `password` (never settable here), `email` (the
    authentication identifier — changing it is an identity operation, not
    an access-management one, and the current architecture has no
    re-verification flow for it), and every raw scope field (derived from
    `role` + `building_id` by logic/user_admin_logic.resolve_scope_for_role,
    never accepted from the client)."""

    full_name: Optional[str] = Field(default=None, min_length=2, max_length=100)
    role: Optional[AdminAssignableRole] = None
    building_id: Optional[str] = None
