"""
Pure unit tests — no database connection required. These exercise the
JWT/password security helpers, the Dijkstra pathfinding logic, and the
role/building permission helper directly, using in-memory objects only.

Run with: pytest backend/tests/test_unit_logic.py -v
"""

import time

import pytest

from core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
    TokenError,
)
from core.auth_deps import user_can_manage_building
from logic.route_calculator import calculate_shortest_path
from models.route_edge_model import RouteEdge
from models.user_model import User


# ---------------------------------------------------------
# Password hashing
# ---------------------------------------------------------

def test_password_hash_and_verify_roundtrip():
    hashed = hash_password("correct-horse-battery-staple")

    assert hashed != "correct-horse-battery-staple"
    assert verify_password("correct-horse-battery-staple", hashed) is True


def test_password_verify_rejects_wrong_password():
    hashed = hash_password("the-real-password")

    assert verify_password("not-the-real-password", hashed) is False


# ---------------------------------------------------------
# JWT access tokens
# ---------------------------------------------------------

def test_create_and_decode_access_token_roundtrip():
    token, expires_at = create_access_token(
        user_id="507f1f77bcf86cd799439011",
        email="admin@example.com",
        role="super_admin",
    )

    payload = decode_access_token(token)

    assert payload["sub"] == "507f1f77bcf86cd799439011"
    assert payload["email"] == "admin@example.com"
    assert payload["role"] == "super_admin"
    assert expires_at.timestamp() > time.time()


def test_expired_access_token_raises_token_error():
    token, _ = create_access_token(
        user_id="507f1f77bcf86cd799439011",
        email="a@b.com",
        role="regular_user",
        expires_minutes=-1,
    )

    with pytest.raises(TokenError) as exc_info:
        decode_access_token(token)

    assert exc_info.value.expired is True


def test_malformed_access_token_raises_token_error():
    with pytest.raises(TokenError):
        decode_access_token("not-a-real-jwt-token")


# ---------------------------------------------------------
# Building-manager scoping
# ---------------------------------------------------------

def _make_user(role, building_ids=None, all_buildings=False):
    return User(
        full_name="Test User",
        email="test@example.com",
        password="hashed",
        role=role,
        building_ids=building_ids or [],
        all_buildings=all_buildings,
    )


def test_super_admin_can_manage_any_building():
    user = _make_user("super_admin")
    assert user_can_manage_building(user, "any-building-id") is True


def test_global_manager_can_manage_any_building():
    user = _make_user("global_manager")
    assert user_can_manage_building(user, "any-building-id") is True


def test_building_manager_scoped_to_assigned_buildings_only():
    user = _make_user("building_manager", building_ids=["b1", "b2"])

    assert user_can_manage_building(user, "b1") is True
    assert user_can_manage_building(user, "b2") is True
    assert user_can_manage_building(user, "b3") is False


def test_building_manager_with_all_buildings_flag():
    user = _make_user("building_manager", all_buildings=True)
    assert user_can_manage_building(user, "any-building-id") is True


def test_regular_user_can_never_manage_a_building():
    user = _make_user("regular_user")
    assert user_can_manage_building(user, "any-building-id") is False


# ---------------------------------------------------------
# Dijkstra shortest-path calculation
# ---------------------------------------------------------

def _edge(from_id, to_id, distance, edge_type="walkway", bidirectional=True, accessible=True, active=True):
    return RouteEdge(
        map_id="map-1",
        from_point_id=from_id,
        to_point_id=to_id,
        edge_type=edge_type,
        distance=distance,
        is_bidirectional=bidirectional,
        is_accessible=accessible,
        is_active=active,
    )


def test_dijkstra_finds_shortest_path_over_multiple_hops():
    edges = [
        _edge("A", "B", 5),
        _edge("B", "C", 5),
        _edge("A", "C", 20),  # longer direct edge — shortest path must avoid this
    ]

    result = calculate_shortest_path(edges, "A", "C")

    assert result is not None
    assert result["path_point_ids"] == ["A", "B", "C"]
    assert result["total_distance"] == 10


def test_dijkstra_returns_none_when_disconnected():
    edges = [
        _edge("A", "B", 5),
        _edge("X", "Y", 5),  # separate, disconnected component
    ]

    result = calculate_shortest_path(edges, "A", "Y")

    assert result is None


def test_dijkstra_respects_bidirectional_flag():
    edges = [_edge("A", "B", 5, bidirectional=False)]

    forward = calculate_shortest_path(edges, "A", "B")
    backward = calculate_shortest_path(edges, "B", "A")

    assert forward is not None
    assert backward is None  # one-way edge — no path back


def test_dijkstra_ignores_inactive_edges():
    edges = [_edge("A", "B", 5, active=False)]

    result = calculate_shortest_path(edges, "A", "B")

    assert result is None
