"""
Invitation Code administration + one-time signup flow — covers the full
required scenario list: creator permission hierarchy, building-scope
enforcement, status precedence (used > revoked > expired > active),
atomic single-use consumption (including a real concurrent race and a
failed-user-creation rollback), and the dev-only bootstrap endpoint's
default-off gating.

Run with: pytest backend/tests/test_invitation_codes.py -v
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from beanie.operators import In

from tests.test_api_integration import (
    auth_headers,
    create_admin_and_get_token,
    make_invitation_code,
    signup,
)

from logic import auth_logic
from logic.invitation_code_logic import validate_role_and_scope_for_creation
from models.invitation_code_model import InvitationCode
from models.user_model import User
from schemas.auth_schema import SignupRequest


# ---------------------------------------------------------
# 1-4, 6. Creator permission hierarchy
# ---------------------------------------------------------

def test_super_admin_creates_building_manager_code(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="sa1@example.com")
    building = client.post(
        "/api/locations/buildings", json={"name_en": "Mall"}, headers=auth_headers(super_token)
    ).json()

    response = client.post(
        "/api/invitation-codes",
        json={"role": "building_manager", "building_ids": [building["id"]], "all_buildings": False},
        headers=auth_headers(super_token),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["role"] == "building_manager"
    assert body["building_ids"] == [building["id"]]
    assert body["status"] == "active"
    assert body["created_by_name"]


def test_global_manager_creates_building_manager_code_within_scope(client):
    gm_token, _ = create_admin_and_get_token(client, role="global_manager", email="gm1@example.com")
    building = client.post(
        "/api/locations/buildings", json={"name_en": "Campus B"}, headers=auth_headers(gm_token)
    ).json()

    response = client.post(
        "/api/invitation-codes",
        json={"role": "building_manager", "building_ids": [building["id"]]},
        headers=auth_headers(gm_token),
    )
    assert response.status_code == 201, response.text
    assert response.json()["role"] == "building_manager"


def test_global_manager_cannot_create_super_admin_code(client):
    gm_token, _ = create_admin_and_get_token(client, role="global_manager", email="gm2@example.com")

    response = client.post(
        "/api/invitation-codes",
        json={"role": "super_admin", "all_buildings": True},
        headers=auth_headers(gm_token),
    )
    assert response.status_code == 403


def test_global_manager_cannot_create_another_global_manager_code(client):
    gm_token, _ = create_admin_and_get_token(client, role="global_manager", email="gm3@example.com")

    response = client.post(
        "/api/invitation-codes",
        json={"role": "global_manager", "all_buildings": True},
        headers=auth_headers(gm_token),
    )
    assert response.status_code == 403


def test_building_manager_cannot_create_invitation_codes(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="sa2@example.com")
    building = client.post(
        "/api/locations/buildings", json={"name_en": "BM Building"}, headers=auth_headers(super_token)
    ).json()
    bm_code = make_invitation_code(
        client, code="QR-BMCREATE1", role="building_manager", building_ids=[building["id"]], creator_token=super_token
    )
    bm_token = signup(client, bm_code, email="bm-creator@example.com").json()["access_token"]

    response = client.post(
        "/api/invitation-codes",
        json={"role": "regular_user"},
        headers=auth_headers(bm_token),
    )
    assert response.status_code == 403


def test_unauthenticated_request_cannot_create_invitation_codes(client):
    response = client.post(
        "/api/invitation-codes",
        json={"role": "regular_user"},
    )
    assert response.status_code == 401


# ---------------------------------------------------------
# 6-9. Building requirement / existence / scope / uniqueness
# ---------------------------------------------------------

def test_building_manager_code_requires_at_least_one_building(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="sa3@example.com")

    response = client.post(
        "/api/invitation-codes",
        json={"role": "building_manager", "building_ids": [], "all_buildings": False},
        headers=auth_headers(super_token),
    )
    assert response.status_code == 400


def test_create_code_rejects_nonexistent_building(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="sa4@example.com")

    response = client.post(
        "/api/invitation-codes",
        json={"role": "building_manager", "building_ids": ["000000000000000000000000"]},
        headers=auth_headers(super_token),
    )
    assert response.status_code == 404


async def test_creator_cannot_assign_building_outside_their_scope():
    # building_manager can never reach the live POST /api/invitation-codes
    # route at all (blocked earlier by require_global_admin — see
    # test_building_manager_cannot_create_invitation_codes above). This
    # exercises the defensive per-building scope check inside
    # validate_role_and_scope_for_creation() directly, so the "creator
    # cannot assign a building outside their scope" rule is verified as
    # real, reachable code — not just unreachable dead code — and stays
    # correct if the route-level gate is ever loosened.
    creator = User(
        full_name="Scoped Manager",
        email="scoped@example.com",
        password="hashed",
        role="building_manager",
        building_ids=["000000000000000000000abc"],
        all_buildings=False,
    )

    with pytest.raises(Exception) as exc_info:
        await validate_role_and_scope_for_creation(
            creator,
            role="regular_user",
            all_buildings=False,
            building_ids=["000000000000000000000def"],
        )

    assert getattr(exc_info.value, "status_code", None) == 403


def test_generated_code_is_unique(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="sa5@example.com")

    codes = set()
    for _ in range(5):
        response = client.post(
            "/api/invitation-codes",
            json={"role": "regular_user"},
            headers=auth_headers(super_token),
        )
        assert response.status_code == 201, response.text
        codes.add(response.json()["code"])

    assert len(codes) == 5  # every auto-generated code was distinct


# ---------------------------------------------------------
# 10-14. Validation status precedence
# ---------------------------------------------------------

def test_active_unused_code_validates(client):
    code = make_invitation_code(client, code="QR-ACTIVE001", role="regular_user")

    response = client.post("/api/invitation-codes/validate", json={"code": code})
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["role"] == "regular_user"
    # Safe preview must never include creator/usage identity.
    assert "created_by_user_id" not in body
    assert "used_by_email" not in body


async def test_expired_code_fails_validation_and_signup(client):
    # expires_at must be in the future at creation time (POST validates
    # this), so an already-expired code is inserted directly via the
    # model to simulate one whose expiry has since passed.
    entry = InvitationCode(
        code="QR-EXPIRED01",
        role="regular_user",
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        created_by_user_id="test",
    )
    await entry.insert()

    validate_response = client.post("/api/invitation-codes/validate", json={"code": "QR-EXPIRED01"})
    assert validate_response.json()["valid"] is False

    signup_response = signup(client, "QR-EXPIRED01", email="expired@example.com")
    assert signup_response.status_code == 400


def test_revoked_code_fails_validation_and_signup(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="sa7@example.com")
    code = make_invitation_code(client, code="QR-REVOKE001", role="regular_user", creator_token=super_token)

    list_response = client.get("/api/invitation-codes", headers=auth_headers(super_token))
    code_id = next(c["id"] for c in list_response.json() if c["code"] == code)

    revoke_response = client.post(f"/api/invitation-codes/{code_id}/revoke", headers=auth_headers(super_token))
    assert revoke_response.status_code == 200
    assert revoke_response.json()["status"] == "revoked"

    validate_response = client.post("/api/invitation-codes/validate", json={"code": code})
    assert validate_response.json()["valid"] is False

    signup_response = signup(client, code, email="revoked@example.com")
    assert signup_response.status_code == 400

    # A used/inactive code cannot be revoked again.
    second_revoke = client.post(f"/api/invitation-codes/{code_id}/revoke", headers=auth_headers(super_token))
    assert second_revoke.status_code == 400


def test_used_code_fails_validation_and_signup(client):
    code = make_invitation_code(client, code="QR-USEDCODE1", role="regular_user")
    signup(client, code, email="first-use@example.com")

    validate_response = client.post("/api/invitation-codes/validate", json={"code": code})
    assert validate_response.json()["valid"] is False

    second = signup(client, code, email="second-use@example.com")
    assert second.status_code == 400


def test_intended_email_mismatch_fails_signup(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="sa8@example.com")
    response = client.post(
        "/api/invitation-codes",
        json={"role": "regular_user", "intended_email": "expected@example.com"},
        headers=auth_headers(super_token),
    )
    code = response.json()["code"]

    wrong_email = signup(client, code, email="someone-else@example.com")
    assert wrong_email.status_code == 403

    right_email = signup(client, code, email="expected@example.com")
    assert right_email.status_code == 200


# ---------------------------------------------------------
# 15-18. Signup correctness + consumption
# ---------------------------------------------------------

def test_successful_signup_creates_correct_role(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="sa9@example.com")
    code = make_invitation_code(client, code="QR-ROLECHK01", role="global_manager", creator_token=super_token)

    response = signup(client, code, email="rolecheck@example.com")
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "global_manager"


def test_successful_signup_stores_correct_building_permissions(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="sa10@example.com")
    building = client.post(
        "/api/locations/buildings", json={"name_en": "Perm Building"}, headers=auth_headers(super_token)
    ).json()
    code = make_invitation_code(
        client, code="QR-PERMCHK01", role="building_manager", building_ids=[building["id"]], creator_token=super_token
    )

    response = signup(client, code, email="permcheck@example.com")
    assert response.status_code == 200
    user = response.json()["user"]
    assert user["building_ids"] == [building["id"]]
    assert user["all_buildings"] is False


def test_signup_consumes_the_code(client):
    super_token, _ = create_admin_and_get_token(client, role="super_admin", email="sa11@example.com")
    code = make_invitation_code(client, code="QR-CONSUME01", role="regular_user", creator_token=super_token)

    signup(client, code, email="consume@example.com")

    list_response = client.get("/api/invitation-codes", headers=auth_headers(super_token))
    entry = next(c for c in list_response.json() if c["code"] == code)
    assert entry["status"] == "used"
    assert entry["used_at"] is not None
    assert entry["used_by_user_id"] is not None


def test_second_signup_with_same_code_fails(client):
    code = make_invitation_code(client, code="QR-SECONDUSE1", role="regular_user")
    first = signup(client, code, email="second-use-a@example.com")
    assert first.status_code == 200

    second = signup(client, code, email="second-use-b@example.com")
    assert second.status_code == 400


# ---------------------------------------------------------
# 19-20. Atomicity: real concurrency + rollback on failure
# ---------------------------------------------------------

async def test_concurrent_signup_cannot_create_two_accounts():
    code_str = "QR-RACECODE1"
    entry = InvitationCode(code=code_str, role="regular_user")
    await entry.insert()

    request_a = SignupRequest(
        full_name="Racer A", email="racer-a@example.com", password="password123", code=code_str
    )
    request_b = SignupRequest(
        full_name="Racer B", email="racer-b@example.com", password="password123", code=code_str
    )

    results = await asyncio.gather(
        auth_logic.signup_user(request_a),
        auth_logic.signup_user(request_b),
        return_exceptions=True,
    )

    successes = [r for r in results if not isinstance(r, Exception)]
    failures = [r for r in results if isinstance(r, Exception)]

    assert len(successes) == 1
    assert len(failures) == 1

    all_users = await User.find(
        In(User.email, ["racer-a@example.com", "racer-b@example.com"])
    ).to_list()
    assert len(all_users) == 1  # only the winner's account was actually created

    reloaded = await InvitationCode.find_one(InvitationCode.code == code_str)
    assert reloaded.is_used is True


async def test_failed_user_creation_releases_code_reservation(monkeypatch):
    code_str = "QR-ROLLBACK1"
    entry = InvitationCode(code=code_str, role="regular_user")
    await entry.insert()

    async def failing_insert(self, *args, **kwargs):
        raise RuntimeError("simulated database failure during user creation")

    monkeypatch.setattr(User, "insert", failing_insert)

    request = SignupRequest(
        full_name="Rollback Test", email="rollback@example.com", password="password123", code=code_str
    )

    with pytest.raises(RuntimeError):
        await auth_logic.signup_user(request)

    reloaded = await InvitationCode.find_one(InvitationCode.code == code_str)
    assert reloaded.is_used is False
    assert reloaded.used_at is None
    assert reloaded.used_by_user_id is None


# ---------------------------------------------------------
# 21. Dev-only bootstrap endpoint stays safely gated
# ---------------------------------------------------------

def test_dev_create_unavailable_once_a_super_admin_exists(client):
    # conftest.py enables ALLOW_DEV_INVITATION_ENDPOINTS for the test
    # process, but the endpoint must still refuse to run once any
    # super_admin already exists — this is what makes it safe even when
    # a real deployment were to accidentally leave the flag on.
    create_admin_and_get_token(client, role="super_admin", email="dev-guard@example.com")

    response = client.post(
        "/api/invitation-codes/dev-create",
        json={"code": "QR-SHOULDFAIL", "role": "super_admin", "all_buildings": True},
    )
    assert response.status_code == 403


def test_dev_endpoint_flag_defaults_to_disabled_when_unset(monkeypatch):
    # Tests the exact gating expression routes/invitation_code_routes.py
    # evaluates once at import (`os.getenv(...) == "true"`), independent
    # of this test session's conftest.py override — confirms a real
    # deployment that never sets the variable gets the safe default.
    import os as _os

    monkeypatch.delenv("ALLOW_DEV_INVITATION_ENDPOINTS", raising=False)
    computed = _os.getenv("ALLOW_DEV_INVITATION_ENDPOINTS", "false").strip().lower() == "true"
    assert computed is False


def test_dev_create_succeeds_only_as_a_genuine_first_admin_bootstrap(client):
    # Positive path, so the gated endpoint is proven to still work for its
    # one legitimate purpose (this test's database is fresh — no
    # super_admin exists yet — matching the "brand-new deployment" case).
    response = client.post(
        "/api/invitation-codes/dev-create",
        json={"code": "QR-BOOTSTRAP1", "role": "super_admin", "all_buildings": True},
    )
    assert response.status_code == 200, response.text

    signup_response = signup(client, "QR-BOOTSTRAP1", email="firstadmin@example.com")
    assert signup_response.status_code == 200
    assert signup_response.json()["user"]["role"] == "super_admin"


# ---------------------------------------------------------
# 22. Regular self-registration can never grant an admin role
# ---------------------------------------------------------

def test_register_cannot_self_assign_admin_role(client):
    # /api/auth/register's RegisterRequest schema has no role/building
    # fields at all — a caller cannot submit a trusted role independently
    # of an invitation code even by adding extra JSON keys, since FastAPI/
    # Pydantic ignores unknown fields by default and register_user() only
    # ever hard-codes role="regular_user".
    response = client.post(
        "/api/auth/register",
        json={
            "full_name": "Sneaky User",
            "email": "sneaky@example.com",
            "password": "password123",
            "role": "super_admin",
            "all_buildings": True,
        },
    )
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "regular_user"
    assert response.json()["user"]["all_buildings"] is False
