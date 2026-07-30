"""
Tests for the expanded, canonical Room/Destination type list (Part 1) and
its backend validation contract (Part 9, scenarios 1-8):

  1. A brand-new canonical value from each new group (retail/public/
     education/navigation) is accepted on create.
  2. A genuinely unsupported value is rejected on create.
  3. Every existing pre-expansion value (the old 10-value hospital list)
     still round-trips unchanged.
  4. The "operating" legacy alias is still accepted on create (never
     silently rewritten to "operating_room").
  5. Updating a room WITHOUT touching room_type never fails, even when the
     room's stored value predates this list entirely (a truly unknown
     legacy string, not even "operating").
  6. Updating room_type TO a new unsupported value is rejected.
  7. Updating room_type to a different, valid canonical value succeeds.
  8. GET responses never crash/omit room_type for a legacy-valued Room.

Run with: pytest backend/tests/test_destination_types.py -v
"""

import pytest

from tests.test_api_integration import auth_headers, create_admin_and_get_token

from constants.destination_types import (
    ALL_ACCEPTED_DESTINATION_TYPES,
    CANONICAL_DESTINATION_TYPES,
    DESTINATION_TYPE_GROUPS,
    LEGACY_ALIAS_DESTINATION_TYPES,
    is_accepted_destination_type,
)
from models.room_model import Room


def _create_building(client, token, name="Dest Type Building"):
    response = client.post(
        "/api/locations/buildings",
        json={"name_en": name},
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_room(client, token, *, building_id, room_type, name="Room"):
    return client.post(
        "/api/rooms",
        json={
            "building_id": building_id,
            "name_en": name,
            "room_type": room_type,
            "floor": 0,
        },
        headers=auth_headers(token),
    )


# ---------------------------------------------------------
# 1 — new canonical values across every new group are accepted
# ---------------------------------------------------------

@pytest.mark.parametrize(
    "room_type",
    [
        "supermarket", "clothing_store", "restaurant", "cafe", "atm",  # retail
        "accessible_restroom", "prayer_room", "customer_service",      # public
        "classroom", "library", "computer_lab",                        # education
        "entrance", "pickup_point",                                    # navigation
        "information_desk", "other",                                   # general
        "treatment_room", "nurses_station",                            # medical
    ],
)
def test_new_canonical_types_are_accepted_on_create(client, room_type):
    token, _ = create_admin_and_get_token(client, email=f"dt-{room_type}@example.com")
    building = _create_building(client, token, name=f"Building {room_type}")

    response = _create_room(client, token, building_id=building["id"], room_type=room_type)
    assert response.status_code == 201, response.text
    assert response.json()["room_type"] == room_type


# ---------------------------------------------------------
# 2 — a genuinely unsupported value is rejected on create
# ---------------------------------------------------------

def test_unsupported_room_type_rejected_on_create(client):
    token, _ = create_admin_and_get_token(client, email="dt-bad-create@example.com")
    building = _create_building(client, token)

    response = _create_room(
        client, token, building_id=building["id"], room_type="spaceship_hangar"
    )
    assert response.status_code == 422, response.text

    all_rooms = client.get("/api/rooms").json()
    assert all(r["building_id"] != building["id"] for r in all_rooms)


# ---------------------------------------------------------
# 3 — every pre-expansion (old hospital-list) value still works unchanged
# ---------------------------------------------------------

@pytest.mark.parametrize(
    "room_type",
    ["emergency", "room", "clinic", "office", "lab", "waiting_area",
     "reception", "imaging", "pharmacy"],
)
def test_old_hospital_list_values_still_accepted(client, room_type):
    token, _ = create_admin_and_get_token(client, email=f"dt-old-{room_type}@example.com")
    building = _create_building(client, token, name=f"Old {room_type}")

    response = _create_room(client, token, building_id=building["id"], room_type=room_type)
    assert response.status_code == 201, response.text
    assert response.json()["room_type"] == room_type


# ---------------------------------------------------------
# 4 — the one old value with no identical-spelling replacement
#     ("operating") is preserved as an explicit legacy alias, never
#     silently rewritten to "operating_room"
# ---------------------------------------------------------

def test_legacy_operating_alias_accepted_and_not_rewritten(client):
    token, _ = create_admin_and_get_token(client, email="dt-operating@example.com")
    building = _create_building(client, token)

    response = _create_room(client, token, building_id=building["id"], room_type="operating")
    assert response.status_code == 201, response.text
    assert response.json()["room_type"] == "operating"


# ---------------------------------------------------------
# 5 — updating a Room WITHOUT touching room_type never fails, even for a
#     truly unknown legacy value that predates this list entirely
# ---------------------------------------------------------

@pytest.mark.asyncio
async def test_update_without_changing_type_never_rejects_unknown_legacy_value(client):
    token, _ = create_admin_and_get_token(client, email="dt-legacy-untouched@example.com")
    building = _create_building(client, token)

    # Bypasses RoomCreate's validator entirely — simulates data that was
    # already stored before this change shipped (must never crash the
    # admin edit form or block unrelated saves).
    room = Room(
        building_id=building["id"],
        name_en="Ancient Room",
        room_type="totally_unknown_legacy_value",
        floor=0,
    )
    await room.insert()

    response = client.put(
        f"/api/rooms/{room.id}",
        json={"description": "Just updating the description"},
        headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["room_type"] == "totally_unknown_legacy_value"
    assert body["description"] == "Just updating the description"


# ---------------------------------------------------------
# 6 — updating room_type TO a new unsupported value is rejected
# ---------------------------------------------------------

def test_update_changing_to_unsupported_type_is_rejected(client):
    token, _ = create_admin_and_get_token(client, email="dt-bad-update@example.com")
    building = _create_building(client, token)

    room = _create_room(
        client, token, building_id=building["id"], room_type="clinic"
    ).json()

    response = client.put(
        f"/api/rooms/{room['id']}",
        json={"room_type": "made_up_type"},
        headers=auth_headers(token),
    )
    assert response.status_code == 400, response.text

    unchanged = client.get(f"/api/rooms/{room['id']}").json()
    assert unchanged["room_type"] == "clinic"


# ---------------------------------------------------------
# 7 — updating room_type to a different valid canonical value succeeds
# ---------------------------------------------------------

def test_update_changing_to_a_different_valid_type_succeeds(client):
    token, _ = create_admin_and_get_token(client, email="dt-good-update@example.com")
    building = _create_building(client, token)

    room = _create_room(
        client, token, building_id=building["id"], room_type="clinic"
    ).json()

    response = client.put(
        f"/api/rooms/{room['id']}",
        json={"room_type": "pharmacy"},
        headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text
    assert response.json()["room_type"] == "pharmacy"


# ---------------------------------------------------------
# 8 — GET responses never crash/omit room_type for a legacy-valued Room
# ---------------------------------------------------------

@pytest.mark.asyncio
async def test_get_never_crashes_on_a_legacy_room_type(client):
    token, _ = create_admin_and_get_token(client, email="dt-get-legacy@example.com")
    building = _create_building(client, token)

    room = Room(
        building_id=building["id"],
        name_en="Legacy Get Room",
        room_type="another_unrecognized_value",
        floor=0,
    )
    await room.insert()

    response = client.get(f"/api/rooms/{room.id}")
    assert response.status_code == 200, response.text
    assert response.json()["room_type"] == "another_unrecognized_value"

    list_response = client.get(f"/api/rooms?building_id={building['id']}")
    assert list_response.status_code == 200
    assert any(r["id"] == str(room.id) for r in list_response.json())


# ---------------------------------------------------------
# Canonical-list integrity (module-level, no DB/client needed)
# ---------------------------------------------------------

def test_canonical_type_list_has_no_duplicates_across_groups():
    seen = set()
    for group_values in DESTINATION_TYPE_GROUPS.values():
        for value in group_values:
            assert value not in seen, f"'{value}' appears in more than one group"
            seen.add(value)


def test_elevator_stairs_escalator_ramp_are_not_room_types():
    # Architecture decision: vertical transitions stay modeled as
    # VerticalConnector documents, never as a Room/destination type.
    for excluded in ("elevator", "stairs", "escalator", "ramp"):
        assert excluded not in CANONICAL_DESTINATION_TYPES
        assert excluded not in LEGACY_ALIAS_DESTINATION_TYPES


def test_is_accepted_destination_type_helper():
    assert is_accepted_destination_type(None) is True
    assert is_accepted_destination_type("supermarket") is True
    assert is_accepted_destination_type("operating") is True
    assert is_accepted_destination_type("not_a_real_type") is False
    assert ALL_ACCEPTED_DESTINATION_TYPES == (
        CANONICAL_DESTINATION_TYPES | LEGACY_ALIAS_DESTINATION_TYPES
    )
