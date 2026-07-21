"""
Shared pytest fixtures for the backend test suite.

Beanie Documents (RouteEdge, User, etc.) need init_beanie() to have run at
least once before they can even be instantiated in memory — not just
before real database calls. This fixture initializes Beanie against an
in-memory mongomock database (mongomock_motor), so the whole suite runs
without any real MongoDB Atlas connection, real credentials, or network
access. It never touches the real quickroute_db.
"""

import asyncio

import pytest
import pytest_asyncio
from beanie import init_beanie
from mongomock_motor import AsyncMongoMockClient

# --- Compatibility shim -------------------------------------------------
# The installed mongomock/pymongo version pair passes newer driver
# keyword arguments (e.g. `authorizedCollections`) into mongomock's
# `list_collection_names`, which doesn't accept them yet. This only
# affects the in-memory test database used here — it has no effect on
# the real app or real MongoDB Atlas connection.
import mongomock.database

_original_list_collection_names = mongomock.database.Database.list_collection_names


def _list_collection_names_compat(self, filter=None, session=None, **_ignored_kwargs):
    return _original_list_collection_names(self, filter=filter, session=session)


mongomock.database.Database.list_collection_names = _list_collection_names_compat
# --------------------------------------------------------------------

from models.user_model import User
from models.invitation_code_model import InvitationCode
from models.building_model import Building
from models.map_model import Map
from models.room_model import Room
from models.route_point_model import RoutePoint
from models.route_edge_model import RouteEdge
from models.location_code_model import LocationCode


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def init_test_database():
    client = AsyncMongoMockClient()

    await init_beanie(
        database=client["quickroute_test_db"],
        document_models=[
            User,
            InvitationCode,
            Building,
            Map,
            Room,
            RoutePoint,
            RouteEdge,
            LocationCode,
        ],
    )

    yield


@pytest.fixture()
def client():
    """
    A FastAPI TestClient that never triggers the app's real `lifespan`
    startup hook (which connects to the real MongoDB Atlas cluster from
    backend/.env). Beanie is already initialized against the in-memory
    mongomock database by `init_test_database` above, so every route
    works normally without ever touching the real quickroute_db.
    """

    from fastapi.testclient import TestClient
    from app import app

    return TestClient(app)


@pytest_asyncio.fixture(autouse=True)
async def clean_collections():
    """
    Each test gets an empty database — mongomock_motor is in-memory and
    fast enough that a full wipe between tests is cheap and keeps tests
    independent of execution order.
    """

    yield

    for model in [
        User,
        InvitationCode,
        Building,
        Map,
        Room,
        RoutePoint,
        RouteEdge,
        LocationCode,
    ]:
        await model.delete_all()
