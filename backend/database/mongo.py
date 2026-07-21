import os
from pathlib import Path

from beanie import init_beanie
from dotenv import load_dotenv
from pymongo import AsyncMongoClient

from models.user_model import User
from models.invitation_code_model import InvitationCode
from models.building_model import Building
from models.map_model import Map
from models.room_model import Room
from models.route_point_model import RoutePoint
from models.route_edge_model import RouteEdge
from models.location_code_model import LocationCode


# المسار الثابت لملف backend/.env
BACKEND_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BACKEND_DIR / ".env"

load_dotenv(dotenv_path=ENV_FILE)


MONGO_URI = os.getenv(
    "MONGO_URI",
    "mongodb://localhost:27017",
)

DATABASE_NAME = os.getenv(
    "DATABASE_NAME",
    "quickroute_db",
)

USING_LOCAL_FALLBACK = "MONGO_URI" not in os.environ


client = AsyncMongoClient(MONGO_URI)


async def init_db():
    try:
        database = client[DATABASE_NAME]

        await init_beanie(
            database=database,
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

        connection_source = (
            "local fallback (MONGO_URI not found in .env)"
            if USING_LOCAL_FALLBACK
            else ".env"
        )

        print(
            f"MongoDB and Beanie initialized successfully "
            f"for database: {DATABASE_NAME} "
            f"(connection source: {connection_source})"
        )

    except Exception as error:
        print(f"MongoDB connection failed: {error}")
        raise