from pymongo import AsyncMongoClient
from beanie import init_beanie

from models.user_model import User
from models.invitation_code_model import InvitationCode
from models.building_model import Building
from models.map_model import Map
from models.room_model import Room
from models.route_point_model import RoutePoint
from models.route_edge_model import RouteEdge

MONGO_URI = "mongodb://localhost:27017"
DATABASE_NAME = "quickroute_db"

client = AsyncMongoClient(MONGO_URI)


async def init_db():
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
        ]
    )

    print("MongoDB and Beanie initialized")